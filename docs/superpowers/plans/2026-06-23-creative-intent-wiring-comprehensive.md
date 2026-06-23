# 接通 CreativeIntent 字段 · 更全面方案（深度尽调修订版）

> 本文是 issue #52 的**更全面方案**，建立在 PR #53 的 [`2026-06-23-creative-intent-wiring.md`](./2026-06-23-creative-intent-wiring.md)（下称"原方案"）之上。原方案的**分层原则、向后兼容铁律、TDD 小步结构正确且应保留**；本文不是推翻它，而是用一次 12-agent 深度尽调（逐条对照真实代码证实/证伪）补上它的**三处假见效、四个缺失的承重步骤、一批漂移行号与一个错误的契约判定**，并把几个字段从"假装接通"改成"诚实接通或明确砍掉"。
>
> **一句话结论**：原方案会把 7 个死字段里的一部分"接通成新的死字段"——单测绿、线上 no-op。更全面方案的核心是**区分真见效 vs 摆设**，并补齐让它真见效（或诚实标注受限）所必需的步骤。

---

## 0. 尽调方法与证据等级

- 8 面并行深读 + 3 条对抗式复核（独立直跑 `plan_insertions` 实测）+ 2 面架构补审，全部 **Read/Grep 真实代码**给 file:line，不臆测。
- 下文每条承重结论都标注证据强度：**【实测】**（跑了代码）/ **【代码确证】**（读到源码）/ **【推断】**（基于代码逻辑推理）。

---

## 1. 调研发现：原方案的三处"假见效"

### 1.1 阶段 1a（scene_type → BGM 加权）= 确定的 no-op 【实测+代码确证】

原方案要在 `_bgm_script_choice_score` 里加 `scene_bonus = _match_count(scene_type, metadata["scene_fit"]) * 30`。三重证伪：

1. **参数语义反了**：`_match_count(haystack, needles)`（`style_planning.py:187-196`）第一参是被搜文本、第二参是关键词列表。原方案把 `scene_type` 当 haystack、`scene_fit` 当 needles，反了。
2. **中英文不可比**：`CreativeIntentArtifact.scene_type` 是 `Literal["hard_ad","ip_persona"]`（`artifacts.py:82`，**英文枚举**）；BGM 候选的 `scene_fit` 是 `["短视频口播","产品介绍","案例讲解"]`（`repository.py:150-151`，**中文标签**）。`_match_count` 要求 `len(needle)>=2` 的子串包含——中文 needle 永远不会出现在英文串 `"hard_ad"` 里，`scene_bonus` 恒为 0。
3. **配套怀疑被证伪、但不改结论**：�['scene_fit','mood'] 这两个 metadata 键**确实存在**（`material_pack_planning.py:476-480` 写入，来自 `BgmSegmentV4` 契约 `media.py:610-614`），所以"键缺失"不成立——但 scene_type 加权 no-op 的真因是"枚举值与中文标签不可比"，比"键缺失"更隐蔽。

> **修正**：要让 scene_type 真改选曲，**必须先加一层 `scene_type 枚举 → 中文场景词` 映射**（如 `hard_ad→["硬广","投流","带货"]`、`ip_persona→["人设","口播","日常"]`），再以映射后的中文词作 needles。裸接 scene_type 字面值 = 假见效。`style_hint`（自由中文文本）可能偶然命中，但不能依赖。

### 1.2 阶段 2（density → max_inserts）= 单向旋钮，调高常为 no-op 【实测】

对抗复核**直接跑了 `plan_insertions`**，实测：

| 场景 | max_inserts 设 1/2/4/8 | 实际放置 | 结论 |
|---|---|---|---|
| 供给充足（8 候选/8 窗口） | 1/2/4/8 | 1/2/4/8 | 向上 binding ✅ |
| 仅 2 候选 | 1/2/4/8 | 1/2/**2/2** | 候选地板封顶，调高 = no-op |
| 8 候选仅 2 空窗 | 1/2/4/8 | 1/2/**2/2** | 窗口地板（每窗至多 1 条） |
| 8 个 <1.5s 短 clip | 1/2/4/8 | **0/0/0/0** | 短 clip 地板，全 0 |
| 向下 4/3/2/1/0 | — | 4/3/2/1/0 | 严格 binding ✅ |

- **真因在 max_inserts 上游**：关键词地板 `_MIN_SIMILARITY=0.05`（`broll_pack.py:36,198`）把候选从 284 砍到个位数，再被 `plan_insertions` 的"每窗口至多 1 条"（`broll_plan.py:421,429-433`）+ 短 clip 地板 `_MIN_INSERT_SECONDS=1.5`（`broll_plan.py:307-308`）二次削。这正是仓库记忆 [b-roll 不足诊断] 的算法级坐实。
- **结论**：density 是**单向旋钮**——调低（low）确定让 b-roll 变稀疏（`broll_plan.py:390/427` 硬截断），调高（high）只在素材+空窗都富余时才生效，真实生产素材下常与 medium 完全相同。
- **未联动 generic coverage**：high 想多插主要靠 Phase2 generic filler，但它仅在 `allow_generic_coverage`（`jobs.py:67` 默认 True）或 `broll_only_v1` 模板时存在（`_broll_policy.py:22-24`）。原方案只调 max_inserts 倍率、不碰这个闸门，在 `allow_generic_coverage=False` 的请求里 high 几乎必然 no-op。

> **修正**：(a) 方案显式写明 density 是单向旋钮，不把 high 当稳定见效；(b) density=high 时**联动放开 `allow_generic_coverage`**（或在 effective_max 抬高时强制 `include_generic_coverage`）；(c) 测试不能只用充足 fixture 证 `high>=medium`，必须补"素材受限"场景断言真实行为；(d) **供给不足导致 high 退化时上报 DegradationNotice**（见 §3.2）。

### 1.3 阶段 3（cover_focus.time_sec）= 时序矛盾的盲猜 【代码确证】

- **致命时序**：`ResolveCreativeIntent`（node_sequence 索引 14）在 TTS（15）、NarrationAlignment（17）、剪辑/渲染**之前**运行。此刻**成片时间轴根本不存在**——LLM 不知道总时长、不知道哪一秒画面好。让它产一个绝对秒数 `time_sec`，与最终成片（因切镜/TTS 时长变化可能变成 9s 或 20s）必然错位，极易落在转场/黑帧，且确定性产出会**稳定复现这张坏封面**。这违背 issue 自身"LLM 产稳定低基数标签、算法做最终决策"的原则。
- **重复造轮**：发布侧 `cover_node.py:66-101` 已用 `extract_frame_at_time(time_sec=GeneratePublishCoverRequest.frame_time_sec)` 让**运营在发布阶段按秒选封面**——这是已落地的确定性运营可控能力。脚本阶段让 LLM 盲猜 time_sec 与之职责重叠且更弱。
- **HDR 回归坑**：`extract_thumbnails`（现状封面用，`ffmpeg.py:219-247`）对 HDR 源做 `HDR_TONEMAP_VF` 转 BT.709；`extract_frame_at_time`（`ffmpeg.py:250-284`）**没有这段**。原方案要把封面切到 `extract_frame_at_time`，会让 HDR 成片封面静默过曝/偏色。

> **修正**：cover_focus 改为 **LLM 只产"封面落在第几个 beat / 哪句钩子句"的低基数语义**，由 export 节点用 `NarrationAlignment` 的 `narration_units.start`（真实时间轴，export 时已可用）换算成 time_sec。切 `extract_frame_at_time` 前先把 HDR tonemap 分支补进去；加"非黑帧/有内容"兜底，失败回退中点。明确 export 默认封面 与 发布侧 `frame_time_sec` 运营覆盖入口的分工。

---

## 2. 调研发现：四个被原方案漏掉的承重步骤

### 2.1 【最重要】消费节点必须 bump `node_version`，否则 resume 复用旧产物跳过新逻辑 【代码确证】

原方案断言"hash 已折入 creative_intent.id，下游消费无需改 hash/幂等"——**结论碰巧对，但理由错，且漏掉了真正必须做的事**：

- `manifest_hash`（`digital_human.py:725-733`）折入 `node_id` + 整个 `request` + `artifact_refs`（各 artifact 的 `.id`），但**不含任何节点代码版本**。
- 更关键：**manifest_hash 比对在生产路径恒被跳过**——`reuse.py:81-82` 的 `expected_input_manifest_hashes` 字段，两处唯一调用（`digital_human.py:1004`、`jobs_runs.py:295`）**都没填**，默认空 dict，比对永远 `None` → skip。`input_manifest_hash` 当前只是写库审计字段，**不参与复用决策**。
- reuse 的**真正安全闸是 `node_version`**（`reuse.py:79-80`），老 run 落库 `"v1"`（`digital_human.py:723`），新跑模板默认 `"v1"`（`jobs.py:20`）。

> **缺失的承重步骤**：当 `broll_planning` / `style_planning` / `export_finished_video` 等节点**开始读 creative_intent** 后，必须 **bump 这些节点的 `node_version`**（`"v1"→"v2"`）。否则一条已完成、被 resume 的老 run 会因 `node_version` 仍匹配而走 `_reuse_prefix`（`digital_human.py:995-1043`）把节点标 `skipped`、复用旧产物，**新逻辑被完全跳过、旧片不会重新消费 creative_intent**。这一步原方案完全没有，必须写进每个消费阶段的落地清单。

### 2.2 resolver 必须真解析 LLM 输出到字段；且 sandbox 下新字段恒默认 【代码确证】

- 现状 `resolve_creative_intent.py:62-66` 只 `CreativeIntentArtifact(intent=result.output.get("intent"))`，7 字段全留默认。这是死字段根因。
- **sandbox provider（`provider_gateway.py:124-137`）只产 `intent.{hook,tone,audience,beats}`**，不产 scene_type/density。**真实 provider 路径（`dashscope.py:158-163`）也只回 `intent`**——除非节点显式从 `result.output` 解析赋值，否则即使扩了 prompt、即使真 LLM，scene_type/density 仍恒默认。

> **影响测试策略**：阶段 0 的单测**不能靠 sandbox 验证 scene_type 取真值**（sandbox 恒吐默认）。必须 stub 一个产 scene_type 的 provider，或直接构造 artifact 注入 state 来测下游消费。原方案 Task 0.3 Step 2 "sandbox provider 仍吐合法 intent"只能验证不炸，验不了新字段。

### 2.3 `creative_intent_ref` 用户直传旁路：扩 prompt 在这条路不生效 【代码确证】

- `digital_human.py:1043-1046` + `resolve_creative_intent.py:15-19`：当 `request.creative_intent_ref` 非空时，**整个 ResolveCreativeIntent 节点被 skip**，7 字段来自被引用的既存 artifact、**不经新 prompt**。若被引用的旧 artifact 是扩字段前产的，scene_type/density 全是默认，下游照样 no-op。
- 好消息：**Web 当前从不设置 `creative_intent_ref`**（`apps/web` 全仓无写入，仅 `schema.d.ts` 有类型），生产主路径不受影响。但 `creative_intent_ref` 是 `ArtifactRef` **引用语义**，填不了内联对象——若未来要让用户内联填 7 字段需另设契约。

> **修正**：方案显式记入风险清单：走 ref 时字段来自既存 artifact、不经新 prompt；主路径不受影响但要在 runbook 标注。

### 2.4 静默降级违背 packages/production 铁律 【代码确证】

`packages/production` CLAUDE.md 明令"降级必须显式上报，禁止静默降级"。原方案每个消费点的"回退默认"全是静默的：density 因供给不足退回实际产出、scene_type 加权恒 0、cover_focus 落在被 clamp/黑帧——这些都是"接了但没生效"的隐性 no-op，无任何 `DegradationNotice`。

> **修正**：新增一个贯穿所有阶段的横切任务，每个消费点的静默回退/恒零加权/坏帧都上报分级 `DegradationNotice` 或 debug warning，让"接了但 no-op"在运行报告里可见。

---

## 3. 调研发现：契约判定错误 + 单一事实源冲突

### 3.1 没有任何阶段触发契约重生成（原方案"4a 是唯一重生成点"错）【实测】

程序化核对 openapi.json（308 schemas）：**`CreativeIntentArtifact` 不在 components/schemas**。openapi 里出现的关键词全部不属于它：

| openapi 行 | 关键词 | 真实归属 | 性质 |
|---|---|---|---|
| `:10812` | `scene_type` | **`ClipSemanticsV4`** | 素材画面标注，非 creative_intent |
| `:12699` | `creative_intent_ref` | `DigitalHumanVideoRequest` | 可选 ArtifactRef 引用 |
| `:22394` | `creative_intent_artifact_id` | `ScriptVersion` | 一个 str id |

- 根因：`CreativeIntentArtifact` 是流水线内部 artifact，落进 `Artifact.data` dict，从不作为 API 请求/响应模型，FastAPI 不生成它。
- **阶段 0**（给已声明字段填值）：**不动 schema.d.ts**。
- **阶段 4a**（`overlay_events: list[dict]→list[OverlayEvent]`）：**当前现状下也不动 schema.d.ts**——`OverlayEvent` 不会被任何进 OpenAPI 的响应模型引用。

> **修正**：原方案"唯一契约重生成点是 4a"是错的——没有任何阶段触发。落地时仍跑一次 `scripts/export_openapi.py && npm run generate:api` 用 `git diff --exit-code` **兜底确认零漂移**（CI 也兜，且本地 key-order 漂移以 CI 为准，见仓库记忆 [openapi-drift-env-sensitive]）。**这反而是好消息**：阶段 4a 不必为强类型化承担 schema 漂移风险——但也因此 `overlay_events` 强类型化对外收益≈0，建议保持 `list[dict]` + 在 `_subtitles` 入口用 Pydantic 校验，别为零收益引入改动面。

### 3.2 三个 `scene_type` 同名异义 + scene_type 已是上游用户输入 【代码确证】

仓库里有**三个互不相干的 `scene_type`**：

1. **内容定位**：`CreativeIntentArtifact.scene_type: Literal["hard_ad","ip_persona"]`（`artifacts.py:82`）——issue#52 说的这个。
2. **素材画面标签**：`ClipSemanticsV4.scene_type: str`（`media.py:486`），VLM 标注，自由文本如 `"studio"/"厨房"/"补漆台"`。
3. **聚类键**：`BrollOverlay.diversity_key` 由 ②聚合（`broll_pack.py:153-154`），驱动 selection ledger 的 cluster 级 recency 降权（**这条链是活的、闭环的**，`finalize_run_report.py`→`_selection.py:86-92`→`recency.py:55-64`）。

**更关键**：`hard_ad/ip_persona` 早就是**脚本生成阶段的用户输入** `persona_mode`（`GenerateScriptWithMemoryRequest.persona_mode`，`cases.py:233`），喂给 LLM 当 prompt 变量（`case_agent_llm.py:77`），但**用完即弃不持久化**（`ScriptVersion`/`ScriptDraft` 无此字段）。让 ResolveCreativeIntent 的 LLM 再盲产一遍 = 劣质第二事实源。

> **修正**：(a) 方案显式声明用的是①，建议把 CreativeIntent 的这个字段**改名 `content_format` 或加命名空间**，与②③解耦防混淆；(b) 评估 scene_type 是否应**从脚本阶段的 `persona_mode` 继承**（持久化到 ScriptVersion 再传给 resolver）而非 LLM 重判——这才是权威来源。

### 3.3 density 无脚本期事实源可继承；Case 的 cut_density 是成片后复盘值 【代码确证】

- `CreativeFeatureVector.cut_density/broll_density`（`cases.py:170`）**唯一产出点**是 `evolution.py:226-236`，从**成片 timeline 反算**（`cuts/duration`），是"这个 case 历史上实际剪多密"的客观复盘值，**不是脚本期可用的输入**。
- 且它**半死**：消费它需要评分卡有 `key="cut_density"` 的维度，但冷启动 `starter_dimensions()`（`rubric.py:52-101`）只有 hook_type/cta_type/script_structure/duration_sec 四维，**不含密度**。
- ResolveCreativeIntent 节点输入**只有 `state.request.script`**（`resolve_creative_intent.py:30,44`），**读不到 case 历史 cut_density**。

> **结论**：density 既不该让 LLM 盲产（无事实依据、与客观 cut_density 打架），Case 层也**没有脚本期 density 可直接继承**（cut_density 是成片后才有）。若坚持做密度驱动，权威路径是"给 resolver 新增输入通道读该 case 的历史 `CreativeFeatureVector.cut_density`，从历史成片密度继承"——但这是更大的改动。**本期务实选择见 §4 决策表。**

---

## 4. 修正后的字段分诊表（核心交付）

> 把 7 个字段按"真见效 / 受限见效 / no-op 摆设 / 砍"分类，每个给出本期建议。

| 字段 | 原方案打算 | 尽调判定 | 本期建议 |
|---|---|---|---|
| **scene_type** → style_preset（1b） | 中→`douyin`/`ip` 两套 ASS | **真见效**（字幕样式肉眼可见），但 style_preset 当前是**死参数**（§5.1），且 scene_type 已是上游 persona_mode | ✅ **做**。优先级判定要修（§5.2）。考虑从 persona_mode 继承 scene_type |
| **scene_type** → BGM 加权（1a） | +30 scene_bonus | **确定 no-op**（中英不可比，§1.1） | ⚠️ **加映射层才做**，否则砍。先证明映射后 `_match_count` 真命中 |
| **style_hint** → BGM 加权（1a） | +20 mood_bonus | 自由中文文本，可能偶然命中，低置信 | 🔸 可做，标注"尽力而为" |
| **density** → max_inserts（2） | low×0.5/high×1.75 | **单向旋钮**，调高常 no-op（§1.2），且无权威事实源（§3.3） | 🔸 **降级做**：只做"调低确定见效 + generic 联动 + 供给不足上报降级"，不承诺 high 稳定增 b-roll |
| **cover_focus.time_sec** → 封面（3） | LLM 产绝对秒 | **时序矛盾盲猜**（§1.3）+ HDR 回归 + 重复造轮 | 🔁 **重做**：LLM 产 beat 语义 + narration_units.start 换算 + 非黑帧兜底 + 补 HDR tonemap |
| **overlay_events** → 强调字幕（4a） | StylePlanning 确定性派生 + 强类型 | **真见效**（最高），但强类型化零对外收益（§3.1） | ✅ **做**，但**保持 `list[dict]`** 不强类型化，省 schema 改动 |
| **closing_cta** | 不接 | 全仓零消费 | ✂️ **明确砍出本期范围** |
| **script_features_hint** | 不接 | 语义最虚、全仓零消费 | ✂️ **直接砍**（建议从契约移除或标 deprecated） |

---

## 5. 修正后的关键实现要点（补原方案的硬伤）

### 5.1 style_preset 当前是死参数——这才是 1b 真正要接的线 【实测确证】

对抗复核独立追完 `style_planning → subtitle_and_bgm_mix → _subtitles` 整条链：

- `style_planning.py:65` 把 `request.subtitle.style_preset` 写进 `SubtitleStylePlan(style_preset=...)`——**唯一一次"写"**。
- `subtitle_and_bgm_mix.py:102` 把整个 `style` dict 透传进 `write_ass_subtitles`，**但调用点不读 style_preset**。
- `write_ass_subtitles`（`_subtitles.py:88-149`）只读 `subtitle.get("font_size")`（:98）和 `subtitle.get("position")`（:106）；全文**无 `"preset"` 字样**（grep exit 1）。ASS Style 行（`_subtitles.py:124-125`）是**硬编码字面量**：`...&H00FFFFFF,&H000000FF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,4,1,2,...`。

> 即 style_preset 端到端是"前端收集→请求体→StylePlanArtifact 存档"，**渲染层完全无视它**。所以 1b 的第一要务不是"scene_type 推 preset"，而是**先把 style_preset 这个死参数接进 `write_ass_subtitles`**（建立 `_PRESET_STYLES` 样式表，`douyin` 逐字节等于现状硬编码行——上面那串就是锁测基准），scene_type 推导只是第二层。原方案 douyin 逐字节锁测的基准串已确认：`&H00FFFFFF` 主色 + `,1,4,1,2,`（Bold=1/Outline=4/Shadow=1/Alignment=2）。

### 5.2 "值==默认即未配置"判定对枚举失效 【代码确证】

- Web 永远发完整 option blocks（`StudioCreatePage.tsx:166-178` `buildJobPayload` 不 omit）：`max_inserts: form.maxInserts`、`style_preset: form.subtitleStyle.trim()||"douyin"`。`BrollOptions`/`SubtitleOptions` 字段都是必填带默认（非 `|None`），契约层**先天无法表达"未配置"**。
- 后果：`style_preset` 默认 `"douyin"` 恰是最高频值，用户**显式选 douyin** 与**没选**不可区分。原方案"值!=默认即显式"会判几乎所有真实请求为"未显式"→intent.scene_type 永远能把字幕改掉，**用户无法锁定 douyin**，优先级第一级名存实亡。
- Web **确实暴露**这俩控件（`StudioCreateSteps.tsx:248` maxInserts number input、`:276` subtitleStyle select 6 枚举 douyin/clean/variety/news/movie/youshe_title_black），所以"用户显式"分支会触发，但因默认=高频值区分度差。

> **修正**：对 style_preset 这种"默认=高频值"枚举放弃值相等判定。三选一：(a) 请求侧加 `*_explicit` flag；(b) 约定 style_preset 始终是用户意图、intent 不接管它（重估 scene_type 是否真该驱动字幕 preset）；(c) 把可被 intent 接管的字段改 `Optional` 默认 `None`，web 仅在用户真改过时填（注意这会触发 OpenAPI 重生成，因为 `DigitalHumanVideoRequest` **在**对外面）。**注意**：选 (c) 与 §3.1 不同——请求契约改 Optional 会真改 schema.d.ts，artifact 内部字段才不会。

### 5.3 行号勘误表

| 原方案引用 | 真实位置 | 说明 |
|---|---|---|
| `broll_planning.py:62` 取 max_inserts | `:91-96` plan_insertions 调用，max_inserts 内联在 `:94` | `:62` 是取 material pack |
| `broll_planning.py:94` 改点 | `:94` `max_inserts=state.request.broll.max_inserts`（确认） | density 介入逻辑插在 `:70-71` 后、`:91` 前 |
| 读取范式"照抄 `export_finished_video.py:171-175`" | 那段**只取 `.id`** 不 model_validate payload | 范式应锚到 Task 0.1 新建的 `load_creative_intent` |
| `ffmpeg.py:250` extract_frame_at_time | `:250-284`（确认），但**缺 HDR tonemap**（extract_thumbnails `:219-247` 有） | 切换前补 tonemap |
| validate_output `registry.py:256` | `registry.py:256-274`（确认只校 intent.hook+beats） | — |
| prompt seed `repository.py:386-401` + binding `:402-407` | `:386-409`（确认 binding `prompt_binding_global_intent` 钉死 `prompt_creative_intent_v1`） | — |

---

## 6. 修正后的分阶段方案

> 保留原方案的 TDD 小步结构（写红测→跑失败→实现→跑绿→提交）。下面只列**相对原方案的增量与修正**；未提及处沿用原方案。**每个消费阶段新增两道强制闸**：①bump node_version（§2.1）；②真机见效闸（§7）。

### 阶段 0 · 基础设施（保留，强化）
- Task 0.1 `load_creative_intent(state)` 助手：**保留**（这是唯一正确的读取范式，删掉"照抄 :171-175"指引）。
- Task 0.2 `_intent_to_artifact` 映射 + 枚举白名单：**保留**，补 `cover_focus`/`overlay_events` 的安全提取。
- Task 0.3 扩 prompt：**保留**，但测试改为 **stub provider**（sandbox 恒吐默认，验不了新字段，§2.2）。补 runbook：新 prompt 版本→publish→re-pin binding + **灰度/一键 re-pin 回滚**。
- **新增 Task 0.4（横切）**：`DegradationNotice` 上报骨架（§2.4），供各消费阶段调用。
- **新增 Task 0.5（命名）**：评估 `scene_type`→`content_format` 改名解耦（§3.2）；评估从 persona_mode 继承。

### 阶段 1b · style_preset 接线（优先级提到最前的真见效项）
- **先接死参数**：`_subtitles.py` 建 `_PRESET_STYLES`，`douyin` 逐字节锁测（基准串见 §5.1），让 `write_ass_subtitles` 真读 `style_preset`。
- 再做 scene_type→preset 推导，**优先级判定按 §5.2 修**。
- bump `style_planning`（或字幕渲染所在节点）`node_version`。真 ffmpeg 逐帧验收（防闪帧，记忆 [frame-exact-render]）。

### 阶段 2 · density → max_inserts（降级为诚实版）
- 按 §5.3 真实行号改 `:94`。density=high **联动 `allow_generic_coverage`**（§1.2）。
- 测试补"素材受限"场景。供给不足致 high 退化时**上报 DegradationNotice**。
- 方案文字写明"单向旋钮"。bump `broll_planning` node_version。

### 阶段 1a · BGM 加权（加映射层才做，否则砍）
- **前置子任务 1a-pre**：建 `scene_type→中文场景词` 映射，单测证明映射后 `_match_count` 真命中（§1.1）。证不通就砍掉 scene_type→BGM，只留 style_hint。
- 参数顺序按 `_match_count(haystack, needles)` 摆对。

### 阶段 3 · cover_focus（重做为 beat 语义）
- LLM 产"封面落在第几个 beat/哪句"；export 用 `narration_units.start` 换算 time_sec。
- 切 `extract_frame_at_time` 前补 HDR tonemap；加非黑帧兜底回退中点。
- 明确与发布侧 `frame_time_sec` 分工。bump export node_version。

### 阶段 4a · overlay_events（确定性派生，不强类型化）
- StylePlanning 确定性派生整句强调（按 beats/关键词在旁白句定位）。
- **保持 `overlay_events: list[dict]`**（§3.1，强类型化零对外收益），在 `_subtitles` 入口用 Pydantic 校验。
- `_subtitles` 加 `Emphasis` 样式行 + Layer1 Dialogue。真 ffmpeg 多样式叠层逐帧验收。bump 相关 node_version。
- 4b（句内逐词高亮）仍单独立项。

### 砍出范围
- `closing_cta`、`script_features_hint`：本期**不接**，方案显式声明为 no-op 字段（避免"已覆盖"错觉）；`script_features_hint` 建议从契约 deprecate。

---

## 7. 每阶段"真机见效闸"（新增，防假接通）

单测绿**不等于**线上见效（§1.1/1.2 已证）。每个消费阶段交付前必须跑一条**真机 run**确认字段真实改变成片：

1. 真凭据 arm + 重启 worker（记忆 [local-provider-smoke-arm-recipe]）。
2. 跑一条真 run，dump `CreativeIntentArtifact.payload`，确认对应字段**非默认**。
3. 确认下游产物真实随之变：BrollPlan 条数 / StylePlan preset / cover 帧 / ASS Emphasis 行**实际变化**。
4. **不见效就降级为"诚实标注受限"**，不假装接通（写进运行报告 DegradationNotice）。

---

## 8. 开放问题（需 review 拍板）

1. **scene_type 驱动**：接受新增"枚举→中文场景词"映射层（唯一能真见效的路）？还是放弃 scene_type→BGM、只让 style_hint 参与？是否从脚本阶段 `persona_mode` 继承 scene_type 而非 LLM 重判？
2. **scene_type 改名**：是否把 `CreativeIntentArtifact.scene_type` 改名 `content_format` 解耦另两个 scene_type？
3. **style_preset 锁定**：用户选了就锁死（intent 永不动 preset），还是接受 intent 在用户没主动改时接管？若要锁定，选 §5.2 的哪个方案（explicit flag / 始终用户意图 / Optional）？
4. **density 手感**：接受"单向旋钮"（调低确定、调高素材不足时无变化）？还是要求 high 稳定增 b-roll（须连带放宽关键词地板/每窗一条/generic，改动面大很多）？
5. **cover_focus**：走"LLM 产 beat 语义 + narration_units.start 换算"（稳健、要改 prompt 产 beat 序号），还是维持"LLM 猜绝对秒"（简单但盲猜易坏帧）？
6. **closing_cta / script_features_hint**：直接砍出范围，还是保留接通（须新设计具体怎么消费）？
7. **用户覆盖入口**：是否为这批 LLM 标签开 Web 请求字段 + BatchItemOverrides（让用户纠正 LLM 误判，会触发 OpenAPI 重生成），还是本期只让 LLM 单方产出、用户无覆盖权？
8. **overlay_events 类型**：保持 `list[dict]`（省 schema、零对外收益）还是强类型化 `OverlayEvent`（更整洁但当前现状下也不触发 schema 重生成）？

---

## 9. 与原方案的兼容性总结

- **保留**：分层原则、向后兼容铁律、`load_creative_intent` 助手、`_intent_to_artifact` 映射、validate_output 宽松、prompt re-pin runbook、TDD 小步结构、阶段 4b 单独立项。
- **修正**：行号勘误（§5.3）；读取范式锚点；契约重生成判定（无阶段触发，§3.1）；density 单向旋钮 + generic 联动；scene_type→BGM 需映射层；cover_focus 改 beat 语义；style_preset 先接死参数 + 优先级判定。
- **新增**：node_version bump（§2.1，最重要）；DegradationNotice 上报（§2.4）；scene_type 命名解耦（§3.2）；真机见效闸（§7）；creative_intent_ref 旁路记录（§2.3）；测试改 stub provider（§2.2）。
- **砍**：closing_cta / script_features_hint / overlay_events 强类型化。

---

## 10. 最终收敛方案（§8 八问已拍板 · 2026-06-23）

> 下表是 §8 八个开放问题的拍板结果，**本节 supersede 上面 §4/§6 的探索性分诊**。方案范围因此大幅收窄——从"接 7 个字段"收敛到"接 3 个 LLM 字段 + 1 个独立死参数修复 + 删 1 个字段 + 砍 3 个字段"。

### 10.1 拍板结果

| # | 开放问题 | 决策 |
|---|---|---|
| 1 | scene_type 驱动 | **放弃 scene_type 驱动**，只让 style_hint 参与 BGM 加权 |
| 1′ | scene_type 字段处置 | **直接删除** `CreativeIntentArtifact.scene_type`（零消费已确认：全仓无 `.scene_type` 读取点、无测试断言） |
| 2 | style_preset 优先级 | **先接死参数 + 用户意图永远优先**（scene_type 不碰 preset；style_preset 始终 = 用户在 UI 的选择） |
| 3 | density | **本期砍掉**（保留字段不接；待未来给 resolver 接通 Case 历史 `cut_density` 再单独立项） |
| 4 | cover_focus | **LLM 产 beat 语义 + export 用 `narration_units.start` 换算 + 非黑帧兜底 + 补 HDR tonemap** |
| 5 | closing_cta / script_features_hint | **都砍出本期**（保留字段不接） |
| 6 | 用户覆盖入口 | **本期不开**，LLM 单方产出（不触发 OpenAPI 重生成） |
| 7 | overlay_events 类型 | **保持 `list[dict]` + `_subtitles` 入口 Pydantic 校验** |

### 10.2 收敛后真正要做的事（4 条）

本期 `CreativeIntentArtifact` 实际驱动剪辑的只剩 **3 个 LLM 字段**：`style_hint`（→BGM）、`cover_focus`（→封面）、`overlay_events`（→强调字幕，确定性派生）。外加 **1 个与 creative_intent 无关的独立死参数修复**：`style_preset`。

**A. style_preset 死参数修复（独立、最高可见收益、不依赖 creative_intent）**
- `_subtitles.py` 建 `_PRESET_STYLES` 样式表，`douyin` 逐字节等于现状硬编码行（基准串：`_subtitles.py:124` `Style: Default,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,4,1,2,...`），让 `write_ass_subtitles` 真读 `subtitle["style_preset"]`。
- 至少补一套可见不同的 preset（如 `news`/`movie`，对齐前端 6 枚举 douyin/clean/variety/news/movie/youshe_title_black）。
- `style_preset` 始终 = `request.subtitle.style_preset`（用户意图），**intent 不接管**。
- 锁测：`douyin` 输出逐字节不变（向后兼容）。真 ffmpeg 逐帧验收防闪帧。
- **bump 字幕渲染所在节点 `node_version`**。

**B. style_hint → BGM 加权（LLM 产，尽力而为）**
- resolver 把 LLM 的 `style_hint`（自由中文文本）提升到 artifact 顶层。
- `_bgm_script_choice_score` 加 `mood_bonus = _match_count(拼接的中文 mood/scene_fit 文本, _string_list(style_hint)) * 权重`，**参数顺序按 `_match_count(haystack, needles)` 摆对**。
- 用户显式 `bgm.bgm_id` 时短路不参与（现状已有）。
- 命中数为 0 时上报 debug（诚实标注尽力而为）。bump `style_planning` node_version。

**C. cover_focus → beat 语义封面（重做）**
- 扩 prompt 让 LLM 产 `cover_focus = {"beat_index": N}` 或 `{"hook": true}`（低基数语义，不产绝对秒）。
- export `_frame_cover`：用 `NarrationAlignment` 的 `narration_units[beat].start` 换算 time_sec，调 `extract_frame_at_time`。
- **先把 `extract_thumbnails` 的 HDR tonemap 分支补进 `extract_frame_at_time`**（`ffmpeg.py`），否则 HDR 封面回归。
- 加非黑帧/有内容兜底，失败回退中点（现状）。无 cover_focus 时完全保持中点（向后兼容）。
- 明确：export 产默认封面，发布侧 `frame_time_sec` 仍是运营覆盖入口。bump export node_version。

**D. overlay_events → 整句强调字幕（确定性派生）**
- StylePlanning 从 narration units + intent.beats 关键词，把"匹配到某 beat 的整句旁白"派生成 `{start,end,text,style:"emphasis"}` 事件（确定性、不让 LLM 产时间轴）。
- `overlay_events` 保持 `list[dict]`，`_subtitles` 入口用 Pydantic 校验。
- `_subtitles.py` 加 `Emphasis` 样式行 + Layer1 Dialogue 循环。真 ffmpeg 多样式叠层逐帧验收。bump 相关 node_version。
- 4b（句内逐词高亮）仍单独立项。

### 10.3 横切任务（贯穿 A–D）

- **删除 `scene_type`**：从 `CreativeIntentArtifact`（artifacts.py:82）移除；确认 `contracts/__init__.py __all__` 无需改（只导出类不导出字段）；grep 复核零引用后删；因 artifact 不在 OpenAPI 面，**不触发 schema.d.ts 重生成**（落地仍跑 export+`git diff --exit-code` 兜底）。
- **resolver 真解析**：`resolve_creative_intent.py` 新增从 `result.output["intent"]` 提取 `style_hint`/`cover_focus` 到 artifact 顶层（`overlay_events` 由 StylePlanning 派生、不在 resolver）。测试用 **stub provider**（sandbox 恒吐默认，验不了新字段）。
- **node_version bump**：A/B/C/D 每个消费节点开始读 creative_intent / 改渲染逻辑后，bump 其 `node_version`（reuse 真闸，§2.1），否则 resume 老 run 复用旧产物跳过新逻辑。
- **DegradationNotice 上报**：BGM 加权命中 0 / cover 落黑帧回退 / style_preset 未知值回退 douyin —— 都上报分级降级，不静默（§2.4）。
- **prompt 扩字段 + re-pin**：prompt 只新增 `style_hint` + `cover_focus`（beat 序号语义）；走新版本→publish→re-pin binding，含灰度/一键 re-pin 回滚。
- **真机见效闸**（§7）：A/B/C/D 各跑一条真 run，确认 preset 真换样式 / BGM 真换曲 / cover 真定格对的帧 / Emphasis 行真出现，不见效就诚实标注。

### 10.4 收敛后字段终态

| 字段 | 终态 |
|---|---|
| `scene_type` | ❌ **删除** |
| `density` | ⏸️ 保留字段、本期不接（未来 Case cut_density 继承再立项） |
| `closing_cta` | ⏸️ 保留字段、本期不接 |
| `script_features_hint` | ⏸️ 保留字段、本期不接（语义最虚，下次 dead-code 清理候选） |
| `style_hint` | ✅ 接通 → BGM 加权（尽力而为） |
| `cover_focus` | ✅ 接通 → beat 语义封面 |
| `overlay_events` | ✅ 接通 → 强调字幕（list[dict]） |
| `intent` | （现状保留） |

> **顺手清理提示**：删 scene_type 后，`density`/`closing_cta`/`script_features_hint` 三个仍是确认死字段。本期按拍板"保留不接"，但它们是下一轮 `/dead-code-cleanup` 的明确候选——若 review 时倾向一次清干净，可在本 PR 一并删除（同样不触发 schema 重生成）。

### 10.5 推荐落地顺序

**A（style_preset 死参数）→ D（overlay_events）→ C（cover_focus）→ B（style_hint BGM）**，删 scene_type 与 resolver 解析作为 A 的前置基础设施一起做。

理由：A 不依赖 creative_intent、独立可见收益最高、最适合先打通"渲染层真读配置"的闭环；D/C 是 creative_intent 的两个真见效项；B 收益最低（自由文本偶然命中）放最后。每步都过 §10.3 横切清单 + §7 真机见效闸。
