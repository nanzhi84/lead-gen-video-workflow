# M6L 施工简报：真出片链路的可持久修复（创意 prompt + 非 strict 对齐软降级）

负责：Codex（执行）/ Claude（架构 + 验收）
分支：`feat/m6l-realrun-durable-fixes`
来源：验收官在演示环境跑真出片（真 MiniMax 人声）时，逐个抓到的真实链路 bug。当前演示已用「在线改 prompt 版本 + 改 binding + 临时禁用 ASR profile」临时绕过，但**这些是运行期临时补丁，重新 bootstrap 会回到坏状态**。本批把修复落到代码/seed，使全新 bootstrap 即可跑通真出片。

## 背景（已验证事实，勿推翻）

真出片链路实测：DashScope LLM ✅ → MiniMax T2A v2 真人声 ✅（产物 minimax-tts.mp3，32kHz）→ 渲染/字幕/导出 ✅，成片 1080×1920/30fps mp4 + 烧录中文字幕 ✅。
两处阻断已定位：

1. **创意意图 prompt 是占位串**：`packages/core/storage/repository.py:251` 把 `prompt_creative_intent_v1` 的 content 设为 `"Summarize script intent as strict JSON."`。真 LLM（qwen-plus）据此返回的 JSON 不含 `hook`/`beats`，`packages/ai/prompts/registry.py:113-124` 的 `validate_output`（schema `creative_intent.output`）要求 `output.intent.hook`(str)+`intent.beats`(list)，于是 `prompt.output_invalid` 硬失败。
   - 注意：`packages/ai/providers/dashscope.py:152` 的 LLM 插件把模型 JSON 直接放到 `output["intent"]`，所以模型须**顶层**输出 `{hook,tone,audience,beats}`（不要再嵌套 intent）。
   - 注意：prompt 渲染用 `str.format` 风格（`{script}` 是变量）。**正文里任何字面 `{`/`}` 都会触发 `prompt.render_error`**——除 `{script}` 外不得出现裸花括号（验收时踩过这个坑）。
2. **非 strict 模式下 ASR 失败仍硬失败**：`packages/production/pipeline/digital_human.py` 的 `_narration_alignment`（约 1012-1130）逻辑是：只要存在可用 ASR profile 且 `tts.uri` 非空就调 ASR，**ASR 失败即 `raise`（约 1029-1034），不分 strict 与否**；估算回退路径（约 1073+）仅在「没有 ASR profile」时才可达。导致 `strict_timestamps=false` 也无法在 ASR 失败时降级出片。
   - 真 ASR（DashScope Paraformer 录音文件识别）是**异步任务 + 由 DashScope 云端下载 file_urls 音频**；本地 MinIO（127.0.0.1:9000）公网不可达 → 任务 `failed`。这属**基础设施前置条件**（需公网可达音频 URL / 公共 OSS），不在本批用代码解决，仅文档化。

## 改动清单

### A. 创意意图 prompt 落库为可用内容（杀掉根因 1）

- A1 `packages/core/storage/repository.py` 第 251 行 `prompt_creative_intent_v1` 的 `content` 改为正式中文 prompt：要求模型**只输出一个 JSON 对象**（顶层含 `hook` 字符串、`tone` 字符串、`audience` 字符串、`beats` 字符串数组 3-6 条），禁止 markdown 代码块、禁止前后缀文字；正文**只允许 `{script}` 一个占位符，不得有其它字面花括号**。参考验收官已验证可用的版本语义（见本简报末尾「可用 prompt 文案」）。
- A2 不动 `provider_seed.py` 里 `prompt_case_agent_script_v1`、`prompt_vlm_annotation_v1`（已是正式内容，brace-safe）。仅核对它们正文除已声明变量外无裸花括号；若有则一并修正。
- A3（可选健壮性）`packages/ai/providers/dashscope.py:219 _parse_json_object`：在 `json.loads` 前剥离 ```／```json 代码围栏与首尾空白（qwen 偶发包裹）。失败仍返回 {}。**低风险、加固用**，可做。

### B. 非 strict 对齐软降级（杀掉根因 2）

- B1 重构 `_narration_alignment`：ASR 失败分支按 strict 区分——
  - `strict_timestamps=True`：维持 `raise NodeExecutionError(asr error, retryable=True)`（strict 必须真对齐）。
  - `strict_timestamps=False`：**不 raise**，落一条 degradation（reason 如 `asr_unavailable_estimated_fallback`）+ warning，落下失败的 `provider_invocation_id`（审计/成本），然后走估算对齐路径产出 alignment/narration（`source` 用估算语义，如 `estimated`，`strict=False`）。
  - 保持「没有 ASR profile / 无 tts.uri」时：strict→raise（estimated not allowed in strict，维持现状），非 strict→估算（维持现状）。
- B2 估算路径的 `NarrationUnitsArtifact.source` 与 `strict` 字段要诚实（估算时 source 不可标 `asr`）。复用既有 `_narration_units_from_segments`/估算分段逻辑，别重写。
- B3 NodeOutput 的 degradations/warnings 用既有机制（spec 27.1 warning code 点分命名）；新增 warning code 若需要，对齐既有命名风格并在发出点登记。

### C. 测试

- C1 `_narration_alignment` 单测：构造「ASR 调用失败」的 mock gateway——
  - 非 strict → 节点 succeeded、产物为估算对齐、记录 degradation + 失败 invocation id；
  - strict → 抛 NodeExecutionError（provider 错误码）。
- C2 seed prompt 单测：对三个 production prompt 的 content 断言 `str.format(content, **{所有声明变量})` 不抛 KeyError/ValueError（即除声明变量外无裸花括号）；creative_intent 用 `{script}`。
- C3（若做 A3）`_parse_json_object` 单测：带 ```json 围栏的内容能解析出 dict。
- C4 全量基线不回退（约 178 单测）。所有 pytest 包 `timeout -k 5 600`，用主仓库 venv：`/home/nanzhi/projects/cutagent-genesis/.venv/bin/python -m pytest`。DB/Temporal 集成你 sandbox 连不上，验收官在外面跑。

### D. 文档

- D1 `docs/ops/` 或 provider 文档加一节：真 DashScope ASR（Paraformer 异步录音文件识别）需要**公网可达的音频 URL**（公共 OSS / 公网端点），本地 MinIO 不行；strict_timestamps 真对齐字幕依赖此前置条件。非 strict 走估算对齐可本地出片。
- D2 记录本批：创意 prompt 修复 + 非 strict 软降级；strict 真对齐留待公网音频托管接入。

## 边界（Out of scope）

- 不接公网 OSS / 不改 ObjectStore 公网寻址（基础设施 + 凭据，单列）。
- 不碰前端、不碰其它 provider 插件契约。
- 演示环境运行期临时补丁（在线 prompt 版本/binding/ASR enable）由验收官管理，不在代码内。

## Verification（验收官执行）

1. 全新 bootstrap（DROP SCHEMA + bootstrap）后，不做任何在线 prompt 补丁，提交一条 `strict_timestamps=false`、真 MiniMax 人声的 run：ResolveCreativeIntent ✅ → TTS ✅ →（ASR 失败软降级估算）NarrationAlignment ✅ → 出片 ✅。
2. `strict_timestamps=true` 同条件：NarrationAlignment 在 ASR 失败时硬失败（错误码为 provider 错误），符合 strict 语义。
3. 全量 + DB + Temporal 三套绿。

## 可用 prompt 文案（验收官已 live 验证 qwen-plus 可产出合规 JSON，供 A1 参考；可润色但须保持 brace-safe）

```
你是资深短视频创意策划。基于下面的口播脚本，提炼创意结构。

严格要求：直接输出一个 JSON 对象（以左花括号开头、右花括号结尾）；禁止使用 markdown 代码块；禁止任何前后缀说明文字。

JSON 必须且只能包含以下字段：
- hook：字符串，一句话开场钩子。
- tone：字符串，整体语气风格。
- audience：字符串，目标受众。
- beats：字符串数组，3 到 6 条，按顺序列出脚本的关键叙事节拍。

脚本：
{script}
```

---

## 验收记录（2026-06-12，验收官：Claude）

**判定：通过并合入**（merge 见 git log）。Codex 实现 A/B/A3/C/D，TDD red→green；提交被 sandbox 只读 .git 阻断，验收官沙箱外 commit（673d6bb）。

验收官独立证据：
- **全量单测独立复跑：183 passed, 23 skipped**（基线 178→183，新增 narration-alignment/seed-prompt-braces/dashscope-fenced-json 测试）。
- 代码核对：creative prompt 内容与 live 验证版一致（brace-safe，仅 {script}）；`_narration_alignment` 把估算逻辑抽成 helper，非 strict ASR 失败→估算降级（带 DegradationNotice reason=asr_unavailable_estimated_fallback + 失败 invocation id + warning），strict 仍 raise；`_parse_json_object` 剥离 ```/```json 围栏。
- 此前演示用「在线 prompt 版本 + binding + 临时禁用 ASR profile」的临时补丁，现已被 A/B 代码化——全新 bootstrap 即可：非 strict 真人声出片不再被创意 prompt 或 ASR 失败阻断。
