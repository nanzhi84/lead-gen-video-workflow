# M6d 施工简报：真 Provider 接入（原版 provider 集）

负责：Codex（执行）/ Claude（架构 + 验收）
分支：`feat/m6d-real-providers`
Spec：第 11 章（Provider 插件/Secrets/Quota）、5.9 ProviderInvocation、9.3 价格表、2.3 provider 错误码。
目标：用原版同款 provider（MiniMax / DashScope / RunningHub-HeyGem）实现真插件，解锁真 TTS、真 ASR、
真素材标注、真口型、真脚本生成。**真插件 + sandbox 插件并存**，按 ProviderProfile 选择；无 key 时
sandbox 仍可跑（测试默认 sandbox，真插件用门控变量）。

## 密钥与测试凭据（验收官已落地，勿入 git）

- 测试 key 在仓库外 `~/.cutagent/provider-keys.env`（验收官持有，Codex sandbox 读不到也不需要读）。
- Codex **不调真实 API**（sandbox 无网络且不该烧钱）——只实现插件 + 写**契约/单测（mock HTTP）**；
  真实 API 连通性由验收官在 sandbox 外用真 key 验证。
- 真插件读密钥统一经 `SecretStore.get(secret_ref)`（packages/core/storage/secret_store.py），
  profile.secret_ref 指向；**插件代码里禁止出现任何明文 key 或 env 直读业务 key**。

## 原版参考（只读，`/home/nanzhi/projects/digital-human-Cutagent/backend/app/`）

- TTS：`services/tts_service.py`、`routers/media/tts.py`（MiniMax T2A，speech-0x；clone/design）
- ASR：`services/asr_service.py`（DashScope Paraformer）
- VL 标注：`services/broll_analysis_runner.py`、`services/video_service.py` 里的 Qwen-VL 调用、
  `config/prompt_library.py` 的视频分析 prompt
- LipSync：`ai/adapters/runninghub_heygem.py`、`tests/test_runninghub_heygem_retry.py`（提交+轮询+重试语义）
- LLM：DeepSeek/DashScope chat（`ai/gateway.py`）
- 抄 API 形状（endpoint/请求体/轮询），不抄架构。

## 改动清单

### A. 插件基础设施

- A1 `packages/ai/providers/` 下每个真插件一个模块，实现 `ProviderPlugin` 协议（invoke(call)->ProviderResult），
  经注入的 SecretStore + httpx 客户端（超时/重试/错误码映射到 spec 2.3：provider.timeout/quota_exceeded/
  auth_failed/remote_failed/unsupported_option）。HTTP 客户端封装统一（不散落）。
- A2 gateway 注册：真插件按 provider_id 注册进 `ProviderGateway.plugins`，与 sandbox 并存；
  invoke 按 profile.provider_id 路由。异步 job 类（lipsync）支持 submit+poll，落 ProviderInvocation
  的 external_job_id/status 流转（prepared→submitted→polling→succeeded，spec 27.2）。
- A3 真插件产出真 artifact：音频/视频/图片落 ObjectStore（真 sha256 + MediaInfo via probe_media），
  不返回假 URI。

### B. 各 capability 真实现

- B1 `minimax.tts`（tts.speech）：T2A 合成真 WAV/MP3 落库；克隆（voice clone）与设计（design）走真 API；
  试听 preview 产出真音频（替换 M6b 的合成正弦占位 + sandbox 假 URI）。usage 记字符数→price catalog 计费。
- B2 `dashscope.asr`（asr.transcribe）：Paraformer 转写，产出真 `audio.alignment`（带词/句级时间戳）→
  NarrationAlignment 的 source 升级到 `asr`/`forced_alignment`（spec 7.7 顺位 2-3）——**这解开 strict 模式**：
  strict_timestamps=true 也能出片（不再被迫非 strict）。
- B3 `dashscope.vlm`（vlm.annotation）：Qwen-VL 视频标注，产出 canonical 标注（片段/质量事件/可用性判定），
  prompt 走 Prompt Registry（把原版视频分析 prompt 录入 seed）；标注失败重试耗尽→asset annotation_failed
  不进可用池（spec 2.3）。rerun/批量标注走真排队（替换 M6/R3 的"立即翻状态位"占位）。
- B4 `runninghub.heygem`（lipsync.video）：portrait track + audio 提交 HeyGem webapp，轮询取结果，
  产出真 `video.lipsync`；超时/失败按 spec 2.3 映射；保留 lipsync.report。
- B5 `dashscope.llm`（llm.chat）：千问 chat，供 case agent 脚本生成/润色真实化（替换 sqlalchemy_learning 的
  f-string 拼接）；script generate/polish 经 Prompt Registry。DeepSeek 作为可选第二 profile（同接口）。

### C. 配置、价格、运营

- C1 provider profiles seed（`configs/provider_profiles.yaml` 或 seed）：为每个真 capability 建 profile，
  environment=prod，secret_ref 指向待创建 secret；sandbox profile 保留为默认（无 key 环境）。
- C2 price catalog seed：录入各 provider 官方价格（MiniMax 按字符、DashScope 按 token/秒、RunningHub 按 job/秒），
  ProviderInvocation 计费生效，成本归因在数据统计页显真数。价格不确定的标 cost_unpriced 待人工核。
- C3 设置页：provider profile 表单能选 capability + 绑定 secret + 填 default_options（模型 id、节点 id 等，
  HeyGem 的 webapp/node id 走 default_options）；voices 克隆/设计 UI 接真端点（R3 已有壳，去掉沙箱禁用态）。

### D. 测试

- D1 每个真插件 mock HTTP 单测：成功/超时/配额/鉴权失败/远端错误各映射正确错误码；usage 解析正确。
- D2 provider contract 测试扩展（tests/providers/）：真插件实现 capability schema、option 校验、secret missing。
- D3 **真连通门控测试** `tests/providers/test_live_providers.py`（`CUTAGENT_RUN_LIVE_PROVIDER_TESTS=1` 门控）：
  验收官用真 key 跑——每个 capability 一个最小真实调用（短文本 TTS、几秒音频 ASR、一张图标注、
  最短 lipsync），断言产物真实可探针。默认 skip。
- D4 既有 116 单测不回退；sandbox 默认路径不变。

## 边界（Out of scope）

- 余额真实轮询（C2 价格够算成本；余额查询单列，可随后补）；M6c 发布/小V猫；前端坦白①②（M6e/M6f）。

## Verification（sandbox 内）

- 全量 pytest（基线 116）+ 新插件 mock 单测全绿；OpenAPI 同步；不碰前端既有页（除 C3 去禁用态）。
- live 门控测试写好默认 skip。

## 验收门（验收官执行，真 key）

1. 设置页建 3 个 secret（minimax/dashscope/runninghub）+ 对应 profiles。
2. `CUTAGENT_RUN_LIVE_PROVIDER_TESTS=1` 跑 live 门控：四 capability 真实产物可探针。
3. 真环境提交一条 run：**真人声音 + 真口型 + ASR 真对齐字幕**的成片，抽帧+听感目检。
4. 一批素材真实自动标注，标注失败的进 annotation_failed。
5. 数据统计页显示真实 provider 成本（非 ¥0）。
6. 全量 + DB + Temporal 三套绿。

---

## 验收记录（2026-06-12，验收官：Claude）

**判定：主体通过并合入**（merge 见 git log），**真连通部分遗留 M6d-fix**。

通过证据：sandbox 默认路径不变（116 单测绿）；重建 schema 后 23 DB 集成绿（seed 21→47 行，含 5 真 profile + 6 价格条目）；**MiniMax TTS 真 key live 连通通过**（真调 API、真音频产出，3s）；5 插件 mock 单测齐全；估算端点按实际 provider 选价（集成修复，见 M6d-fix(estimate) commit）。

真连通遗留（→ M6d-fix）：
- **DashScope ASR 真连通失败**：插件调了虚构同步端点 `/api/v1/services/audio/asr/recognition`，但 Paraformer 录音文件识别是**异步任务 API**（提交 task→轮询→下载结果 JSON）。mock 只验形状测不出，真 key live 抓到。修复须参照原版 `backend/app/services/asr_service.py` 的调通实现。这是「strict 字幕修真」的关键能力，优先级高。
- VLM（qwen-vl，OpenAI 兼容 chat，疑同步可能 OK）、HeyGem（已是异步轮询架构）真连通待真素材逐个验。

验收方法论价值：真连通验证（真 key + 真素材 live 门控）抓到了 mock 单测无法发现的 API 契约级 bug——这类 provider 接入必须真 key 验收，不能只信 mock。
