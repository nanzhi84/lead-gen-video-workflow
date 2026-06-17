# 仅 B_roll 模式（`broll_only_v1`）设计

> Status: Approved (2026-06-17) · Author: 架构 = Claude，执行 = Codex
> 关联：`packages/production` 16 节点流水线、`docs/树影_Cutagent_CleanSlate重写Spec_v3` §2/§9

## 1. 目标与范围

新增一种内容模式：**画外音 + B_roll 铺满、完全不出现数字人**。

- **保留旁白**：TTS 读脚本做画外音、`NarrationAlignment` 出 narration_units 供字幕与 B_roll 锚点；字幕烧录、BGM 垫底照旧。
- **不规划 A_roll**：完全不跑 `PortraitPlanning` / `PortraitTrackBuild` / `LipSync`。
- **B_roll 当底层主轨铺满整段**：不再是稀疏插片（overlay），而是首尾相接覆盖 `[0, D]`（D = TTS 音频时长）。
- **素材不足 = 硬失败**：可选 B_roll 源总时长 < 目标时长时显式 `NodeExecutionError`，不静默降级（符合 spec §9）。

### 非目标（本期不做）

- **纯静音 / 无旁白模式**：会动到 narration_units 这条"时序脊柱"，跨 4+ 节点，留作 `broll_only_silent_v?` 的后续增量。本设计刻意把 narration 保留，使改动局部化。
- 修改 `digital_human_v2` 的任何既有行为。

## 2. 架构原则（解耦与拓展性，必须守住）

用户的硬约束：**不破坏现有架构的解耦性与拓展性**。本设计据此采用「新模板 + 复用 handler + 新增专用节点」而非「在核心节点里塞 if/else 模式分支」。

1. **新模板，不污染核心节点**：注册第二个 `WorkflowTemplate broll_only_v1`，`digital_human_v2` 的节点代码一行不改。
2. **节点 handler 全局复用**：`NODE_HANDLERS` 是按 `node_id` 的全局分发表；复用的 10 个节点直接共享，新模板只是换一条 `NODE_SEQUENCE` + 注册 3 个新 `node_id`。
3. **共享逻辑下沉为纯函数**：timeline 帧栅格/校验、B_roll 选材、montage 渲染等可复用逻辑抽成 `packages/planning` / `packages/media` 里的纯函数；节点只做编排，不互相 import。
4. **模板选择走数据，不走分支**：用既有的 `request.workflow_template_id` 当模式选择器 + 一个 `template_for(id)` 注册表；杜绝在 service / adapter 里写 `if mode == ...`。
5. **契约最小改动**：请求 shape 不变（不新增模式字段），靠 `workflow_template_id` 分发 → 几乎零 OpenAPI/schema 漂移。

## 3. 节点序列

```
broll_only_v1 (13 节点):
 1 ValidateRequest        复用（+ mode 校验扩展，见 §6）
 2 LoadCaseContext        复用
 3 ResolveCreativeIntent  复用（可 skip via creative_intent_ref）
 4 TTS                    复用 —— audio_tts，时长 D = 时间骨架来源
 5 MaterialPackPlanning   复用 —— 排 broll / bgm / font 候选
 6 NarrationAlignment     复用 —— narration_units（字幕 + B_roll 锚点时序）
 7 BrollCoveragePlanning  【新】铺满 [0,D] 的有序选片；素材不足 → 硬失败
 8 StylePlanning          复用 —— BGM / 字幕 / 字体
 9 BrollTimelinePlanning  【新】时长锚 audio_tts；B_roll 当 base 轨；校验全覆盖
10 BrollRenderBase        【新】ffmpeg 把 B_roll 拼接铺满 → video_rendered
11 SubtitleAndBgmMix      复用 —— 烧字幕 + 混 TTS 音 + BGM → video_final
12 ExportFinishedVideo    复用 —— 成片 + 封面 + publish_package
13 FinalizeRunReport      复用 —— 报告 + 选材 ledger + ephemeral GC
```

砍掉的 A_roll 节点：`PortraitPlanning`、`PortraitTrackBuild`、`LipSync`。

`digital_human_v2`（对照，16 节点）：…PortraitPlanning, BrollPlanning, StylePlanning, TimelinePlanning, PortraitTrackBuild, LipSync, RenderFinalTimeline…

## 4. 数据流（画外音 B_roll-only）

```
script
  → TTS                    : audio_tts（时长 D）
  → NarrationAlignment     : narration_units（覆盖 [0,D] 的文本+时序）
  → BrollCoveragePlanning  : plan_broll（有序片段铺满 [0,D]，末片裁切；不足→fail）
  → BrollTimelinePlanning  : plan_timeline + plan_render
                              total_frames = round(D * fps)
                              单一 'broll' base 轨，校验 [0,total_frames] 无空隙/无重叠
  → BrollRenderBase        : video_rendered（B_roll 拼接铺满，scale 到 WxH@fps）
  → SubtitleAndBgmMix      : video_final + subtitle_ass（烧 narration 字幕；混 TTS + BGM）
  → ExportFinishedVideo    : video_finished + cover_image + publish_package
  → FinalizeRunReport      : 报告 + ledger + GC
```

**音频**：声音只来自 TTS（画外音）+ BGM（StylePlanning 选、SubtitleAndBgmMix 混）。B_roll 片段自带音轨**静音**（与现状一致）。

## 5. 新增组件契约

### 5.1 `packages/planning/material/broll_plan.py::plan_coverage(...)`（纯函数）

与既有 `plan_insertions` 并列，**不改 `plan_insertions`**。

- 输入：候选片段（已 `rank_broll_candidates` 排序，带 source 时长/相关性/diversity_key/recency）、目标时长 `target_sec`、narration units（用于相关性与锚点）、`min_segment_duration`。
- 行为：贪心/确定性地挑选有序片段，使累计时间轴时长 == `target_sec`（末片裁切到边界）；优先相关性高、多样性、recency 未降权者；**确定性，不随机**。
- 输出：有序 `CoverageSegment` 列表（`timeline_start/end`、`source_start/end`、asset/clip id、reason、confidence、matched_keywords、scene_name、diversity_key）。
- 失败：可选源总时长 < `target_sec`（含容差）→ 返回信号让节点抛 `material_insufficient_broll`（硬失败）。

### 5.2 `packages/media/rendering/timeline.py::render_broll_montage(...)`（纯函数，**最大风险点**）

与既有 `render_video_timeline` 并列，**不改 `render_video_timeline`**。

- 输入：有序 B_roll 段（每段 source 文件 + in/out）、`total_frames`、`width`、`height`、`fps`、`artifact_path` 解析器。
- 行为：每段 scale/pad 到 `WxH`、按时间轴顺序拼接（ffmpeg concat 或顺序 trim+setpts），输出恰好 `total_frames` 帧的无声视频；末段裁切对齐。
- 输出：渲染文件路径；交给 `validate_rendered_output` 校验帧数/尺寸/fps。
- 单测断言：`输出帧数 == total_frames`，尺寸/fps 正确。

### 5.3 三个新节点（`packages/production/pipeline/nodes/`）

均为纯 `run(ctx: NodeContext) -> NodeOutput`，输入读 `ctx.state`、输出经 `ctx.artifact(...)`，跨节点只走 `NodeContext`。

- `broll_coverage_planning.py` → `ArtifactKind.plan_broll`（schema `BrollPlanArtifact.v1`，复用既有 artifact 类型；覆盖式语义体现在 payload 段全覆盖）。
- `broll_timeline_planning.py` → `ArtifactKind.plan_timeline` + `ArtifactKind.plan_render`。复用从 `timeline_planning.py` 抽出的帧栅格/校验 helper（见 §7 重构）。
- `broll_render_base.py` → `ArtifactKind.video_rendered`（uri-only，tier=ephemeral，与 `render_final_timeline` 一致）。

## 6. 接线与契约

- `node_sequence.py`：新增 `BROLL_ONLY_SEQUENCE`（13）+ `WORKFLOW_TEMPLATE_NODE_COUNTS["broll_only_v1"] = 13`。
- `digital_human.py`：新增 `broll_only_template()` + `template_for(workflow_template_id)` 注册表（`{"digital_human_v2": digital_human_template, "broll_only_v1": broll_only_template}`）；`NODE_HANDLERS` 新增 3 个 handler。新模板里有 provider 副作用的节点（TTS、ResolveCreativeIntent）保留 `idempotency_key`，否则 reuse 拒绝复用。
- `apps/api/services/jobs_runs.py:98`：`template = digital_human_template()` → `template = template_for(request.workflow_template_id)`。
- `packages/core/workflow/temporal_adapter.py`（`_template_from_run` / `_workflow_payload`）：用同一注册表重建模板 → parity 断言对新模板成立。
- **契约**：`DigitalHumanVideoRequest` shape 不变。`workflow_template_id` 已是 `str`（默认 `"digital_human_v2"`），Web 发 `"broll_only_v1"` 即切模式 → 无 OpenAPI/schema 改动。
  - `ValidateRequest` 扩展（mode-aware，但读 `request.workflow_template_id`、不在节点里硬编码模式名分支逻辑——通过传入的 template 已经天然只跑 13 节点）：在 `broll_only_v1` 下要求 `broll.enabled` 为真；portrait/lipsync 选项忽略（不报错，向后兼容默认值）。
  - 若后续要让 UI 显式区分，可把 `workflow_template_id` 升级成 `Literal`——**本期不做**（那会触发 schema 漂移）。

## 7. 针对性重构（"改到的代码顺手改好"，不做无关重构）

把 `timeline_planning.py` 里与 portrait 无关的纯逻辑（帧换算 `to_frame`、每轨 overlap/越界/负时长校验、`TimelineTrackSegment` 组装、`TimelineValidationReport`）抽成 `pipeline/_timeline_grid.py`（或 `packages/planning/editing` 下）纯函数。`digital_human_v2` 的 `TimelinePlanning` 与新 `BrollTimelinePlanning` 都引用，避免复制粘贴、保持单一事实源。**抽取必须保持 `digital_human_v2` 行为逐字节不变**（由既有 production/workflow 测试守护）。

## 8. 错误处理与降级

| 场景 | 行为 |
|---|---|
| B_roll 源总时长 < 目标 D | `BrollCoveragePlanning` 抛 `NodeExecutionError(material_insufficient_broll)`，run 失败（硬失败，**不**降级） |
| TimelinePlanning 校验出空隙/重叠/越界 | 抛 `render_invalid_timeline`（理论上 coverage 已保证不发生，作纵深防御） |
| ffmpeg 渲染失败 | `BrollRenderBase` 抛 `NodeExecutionError(exc.error_code)`，与 `render_final_timeline` 一致 |
| BGM / 字幕不可用 | 沿用 `StylePlanning` / `SubtitleAndBgmMix` 既有降级（soft_degrade，显式上报） |

硬失败策略与现状 `portrait_insufficient_policy=hard_fail` 对齐；用户已确认。

## 9. Web

`apps/web/src/pages/studio/StudioCreatePage.tsx`：加模式开关「数字人口播 / 仅B_roll画外音」。选仅 B_roll 时隐藏 portrait/lipsync 控件，保留 脚本/配音/B_roll/字幕/BGM；`buildJobPayload` 发 `workflow_template_id="broll_only_v1"`。`RunConfigSummary` 已含该字段，run 详情天然展示。

## 10. 测试

- 单测：`plan_coverage`（全覆盖/有序/裁切/不足即失败/确定性）、`render_broll_montage`（帧数/尺寸/fps）、抽出的 `_timeline_grid` helper。
- 节点测试：`broll_coverage_planning` / `broll_timeline_planning` / `broll_render_base` 各一。
- 工作流测试：`broll_only_v1` 端到端（memory backend / sandbox）出 `video_finished`；新模板 parity guard（对齐 883c0b9 既有 parity 测试风格）；模板内 reuse/resume。
- 回归：`digital_human_v2` 全套 production/workflow 测试不受影响（重构守护）。
- 门禁：`scripts/ci_gate.sh` 绿（需 PG 55432 + Temporal 7233 + MinIO）。

## 11. reuse / resume / parity

- 模板内 reuse 稳定（节点列表按模板固定）。
- Job/run 的 `workflow_template_id` 不可变 → resume 用同一模板重建，`temporal_adapter` 的 parity 断言成立。
- 跨模式 resume 不允许（不同模板 = 不同节点列表）；由 parity 断言自然挡住。

## 12. 解耦/拓展性自检（交付验收项）

- [ ] `digital_human_v2` 的节点文件与模板定义**零改动**（除从 `timeline_planning` 抽 helper，且行为不变）。
- [ ] 无任何 service/adapter/节点内出现 `if template_id == "broll_only_v1"` 式业务分支（一律走注册表/数据）。
- [ ] 新节点之间不互相 import，只经 `NodeContext` + 共享纯函数。
- [ ] 契约 shape 未变、`schema.d.ts` 无漂移（若动了契约则 `export_openapi` + `generate:api` 重生成并提交）。
- [ ] 新增「纯静音」模式时只需再注册一个模板 + 复用本期纯函数，无需回改本期代码（拓展性验证）。
