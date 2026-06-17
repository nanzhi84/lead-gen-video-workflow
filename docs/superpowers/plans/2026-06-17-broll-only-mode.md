# 仅 B_roll 模式（`broll_only_v1`）实现计划

> **For agentic workers / Codex:** 按任务顺序逐个执行，每个任务**测试先行（TDD）**、独立可测、独立提交。本计划由架构方（Claude）编写并验收；你（Codex）只在工作树 `.claude/worktrees/broll-only-mode` 内编辑 + 跑测试验证，**不要 commit / push / 改 git 状态**（由 Claude 提交并清理）。设计事实源：`docs/superpowers/specs/2026-06-17-broll-only-mode-design.md`。

**Goal:** 新增 `broll_only_v1` 工作流模板：画外音（TTS）+ B_roll 铺满整段、完全不规划/不渲染数字人（A_roll），素材不足即硬失败。

**Architecture:** 新模板复用 10 个既有节点 handler（按 node_id 全局分发），新增 3 个 B_roll 专用节点 + 2 个共享纯函数；模板选择走 `workflow_template_id` + 注册表，**不在核心节点/service 里写模式 if/else**。`digital_human_v2` 行为零改动。

**Tech Stack:** Python 3.12 · Pydantic v2 契约 · FastAPI · Temporal · ffmpeg（`packages/media`）· pytest。前端 React/Vite（仅 1 个任务）。

## Global Constraints（每个任务都隐含遵守）

- **不改 `digital_human_v2` 既有行为**：节点文件、模板定义逐字节不变；唯一例外是 Task 1 从 `timeline_planning.py` 抽 helper，且必须行为不变（由既有 production/workflow 测试守护）。
- **无业务级模式分支**：禁止任何 `if workflow_template_id == "broll_only_v1"` 式分支散落在 service/adapter/节点；模式差异一律通过「传入哪个 template / 跑哪条 NODE_SEQUENCE」体现。
- **节点是纯 `run(ctx)`**：输入读 `ctx.state`，输出经 `ctx.artifact(...)`；跨节点只走 `NodeContext`，新节点之间不互相 import。
- **确定性、不随机**；**降级必须显式上报 `DegradationNotice`**；**素材不足硬失败、不静默降级**（spec §9）。
- **契约最小改动**：请求 shape 不变，靠既有 `workflow_template_id: str` 分发；除非确有必要不动 OpenAPI/`schema.d.ts`（若动则 `python scripts/export_openapi.py && (cd apps/web && npm run generate:api)` 重生成并纳入提交）。
- **领域类型唯一来源** `packages/core/contracts`；复用既有 `ArtifactKind`（`plan_broll` / `plan_timeline` / `plan_render` / `video_rendered`）与既有 artifact schema 版本号。
- **测试运行方式（worktree）**：`PYTHONPATH=$PWD CUTAGENT_STORAGE_BACKEND=memory CUTAGENT_ALLOW_SANDBOX_FALLBACK=1 /home/nanzhi/projects/cutagent-genesis/.venv/bin/python -m pytest <targets>`。

---

### Task 1: 抽出 timeline 帧栅格/校验 helper（行为不变重构）

**Files:**
- Create: `packages/production/pipeline/_timeline_grid.py`
- Modify: `packages/production/pipeline/nodes/timeline_planning.py`（改为调用 helper，逻辑等价）
- Test: `tests/production/test_timeline_grid.py`（新增）；回归 `tests/production`、`tests/workflow`

**Interfaces — Produces（后续 Task 5 依赖这些精确签名）:**
```python
# packages/production/pipeline/_timeline_grid.py
from packages.core.contracts.artifacts import TimelineTrackSegment, TimelineValidationReport

def to_frame(seconds: float, fps: int) -> int: ...

# raw_segments: list[dict]，每个含 track_id/segment_id/asset_ref/start_sec/end_sec/
#   source_start_sec/source_end_sec/timeline_start_frame/timeline_end_frame/
#   source_start_frame/source_end_frame（None 表示按秒回退）
def build_tracks(raw_segments: list[dict], fps: int) -> list[TimelineTrackSegment]: ...

def validate_timeline(raw_segments: list[dict], fps: int, total_frames: int) -> TimelineValidationReport:
    """返回 checks={overlap,negative_duration,out_of_bounds}；valid = 三者皆 OK。
    与 timeline_planning.py 现行判定逐项等价（per-track 排序后比较）。"""
```

- [ ] **Step 1**：读 `timeline_planning.py:29-130`，把 `to_frame`/`timeline_start`/`timeline_end`/`source_start`/`source_end`、negative/out_of_bounds/overlap 判定、`TimelineTrackSegment` 组装、`TimelineValidationReport` 构造原样搬进 `_timeline_grid.py` 的上述函数。
- [ ] **Step 2（test first）**：写 `tests/production/test_timeline_grid.py`，用一组 portrait+broll raw_segments 断言：正常→`valid=True`；构造 overlap / 越界 / 负时长各触发对应 check=False。
- [ ] **Step 3**：跑新测试 → 失败（函数未定义）。
- [ ] **Step 4**：让 `TimelinePlanning.run` 改调 `_timeline_grid` 的函数，删除其内联副本；保持 `plan_timeline` + `plan_render` 输出**逐字段一致**。
- [ ] **Step 5**：`pytest tests/production tests/workflow -q` 全绿（**回归守护：digital_human_v2 行为不变**）；`tests/production/test_timeline_grid.py` 绿。
- [ ] **Step 6**：交回 Claude 提交（消息见末尾「提交分组」）。

**验收（Claude）**：diff 里 `timeline_planning.py` 仅是「内联逻辑 → 调 helper」的等价替换，无语义变化。

---

### Task 2: `plan_coverage` 纯函数（B_roll 铺满选片）

**Files:**
- Modify: `packages/planning/material/broll_plan.py`（新增函数，**不改 `plan_insertions`**）
- Modify: `packages/planning/material/__init__.py`（导出 `plan_coverage`、`CoverageSegment`）
- Test: `tests/planning/test_broll_coverage.py`（新增）

**Interfaces — Consumes:** 既有 `rank_broll_candidates(...) -> list[BrollCandidate]`（含 source 时长、relevance、diversity_key、recency 信息）、`NarrationUnit`。先读 `broll_plan.py` 现有 `plan_insertions` 与 `_candidate.py` 确认候选字段名。
**Produces（Task 4 依赖）:**
```python
# packages/planning/material/broll_plan.py
from dataclasses import dataclass

@dataclass(frozen=True)
class CoverageSegment:
    asset_id: str
    clip_id: str
    timeline_start: float
    timeline_end: float
    source_start: float
    source_end: float
    reason: str
    confidence: float
    matched_keywords: tuple[str, ...]
    scene_name: str
    diversity_key: str

@dataclass(frozen=True)
class CoveragePlan:
    segments: tuple[CoverageSegment, ...]
    covered_sec: float
    sufficient: bool          # 累计 source 时长是否 >= target（含容差）

def plan_coverage(
    *,
    candidates,               # rank_broll_candidates 的输出（已按相关性/多样性/recency 排序）
    units,                    # list[NarrationUnit]，用于锚点相关性 + 末段对齐
    target_sec: float,
    min_segment_duration: float,
    tolerance_sec: float = 0.04,  # 约 1 帧@25fps，避免浮点边界误判
) -> CoveragePlan: ...
```

**行为规约**：确定性地按排序顺序取片铺满 `[0, target_sec]`：每片取用时长 ≥ `min_segment_duration`、不超过其 source 可用时长；首尾相接（`segment[i].timeline_end == segment[i+1].timeline_start`）；末片裁切到 `target_sec`。若**所有候选 source 总可用时长 < target_sec − tolerance** → `sufficient=False`（segments 可为已选的部分，节点据此硬失败）。**不重复用同一 clip 来凑时长**（除非候选本就允许；本期不重复，宁可 `sufficient=False`）。同输入同输出（确定性）。

- [ ] **Step 1（test first）**：`tests/planning/test_broll_coverage.py`：
  - 充足：候选总时长 > target → `sufficient=True`，`segments` 首尾相接、`covered_sec ≈ target`、末片被裁切、相邻无缝。
  - 不足：候选总时长 < target → `sufficient=False`。
  - 确定性：同输入两次调用结果相等。
  - 顺序：高相关性候选优先入选。
- [ ] **Step 2**：跑测试 → 失败。
- [ ] **Step 3**：实现 `plan_coverage` + dataclass，导出。
- [ ] **Step 4**：`pytest tests/planning/test_broll_coverage.py -q` 绿；`pytest tests/planning -q` 不回归。
- [ ] **Step 5**：交回 Claude 提交。

---

### Task 3: `render_broll_montage` 纯函数（B_roll 拼接铺满渲染）

**Files:**
- Modify: `packages/media/rendering/timeline.py`（新增函数，**不改 `render_video_timeline`**）
- Modify: `packages/media/rendering/__init__.py`（导出 `render_broll_montage`）
- Test: `tests/media/test_broll_montage.py`（新增；按 `tests/media` 既有 ffmpeg 测试模式，需要本地 ffmpeg）

**Interfaces — Produces（Task 6 依赖）:**
```python
# packages/media/rendering/timeline.py
from pathlib import Path
from collections.abc import Callable

def render_broll_montage(
    *,
    segments: list[dict],     # 有序，每段含 asset_id/source_start/source_end/timeline_start/timeline_end
    output_path: Path,
    total_frames: int,
    width: int,
    height: int,
    fps: int,
    source_artifact_for_asset: Callable[[str], object],  # 同 render_video_timeline 的解析回调
    artifact_path: Callable[[object], Path],
) -> None:
    """按时间轴顺序把每段 scale+pad 到 WxH、trim 到其时长、顺序拼接，输出恰好 total_frames 帧的【无声】视频。末段裁切对齐 total_frames。"""
```

**实现提示（Codex 自行落地，参考 `render_video_timeline` 现有 ffmpeg 用法与 `packages/media/video/ffmpeg.py`）**：每段 `scale=w:h:force_original_aspect_ratio=decrease,pad=w:h:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=fps`，再 `concat` filter 串接；统一 `-an`（去音轨，声音后续由 SubtitleAndBgmMix 注入）；用 `-frames:v total_frames` 或对末段精确 trim 保证总帧数。失败抛 `FfmpegCommandError`。

- [ ] **Step 1（test first）**：`tests/media/test_broll_montage.py`：用 2–3 个 seed 媒体片段渲染，断言 `validate_rendered_output(out, expected_frames=total_frames, expected_width=w, expected_height=h, expected_fps=fps)` 通过（**核心断言：帧数 == total_frames**）。
- [ ] **Step 2**：跑 → 失败。
- [ ] **Step 3**：实现 `render_broll_montage`。
- [ ] **Step 4**：`pytest tests/media/test_broll_montage.py -q` 绿；`pytest tests/media -q` 不回归。
- [ ] **Step 5**：交回 Claude 提交。

---

### Task 4: `BrollCoveragePlanning` 节点

**Files:**
- Create: `packages/production/pipeline/nodes/broll_coverage_planning.py`
- Test: `tests/production/test_broll_coverage_planning.py`（新增）

**Interfaces:**
- Consumes：`ctx.state.require(ArtifactKind.plan_material_pack)`、`ctx.state.require(ArtifactKind.narration_units)`、`ctx.state.require(ArtifactKind.audio_tts)`（取 `media_info.duration_sec` 作 target）、`ctx.repository.annotation_v4_for_asset`、`ctx.repository.recent_selections`、`rank_broll_candidates`、`plan_coverage`。
- Produces：`ArtifactKind.plan_broll`（schema `"BrollPlanArtifact.v1"`，payload 为铺满 segments；复用 `BrollPlanArtifact`，`enabled=True`）。

**行为**：参照 `broll_planning.py` 取候选 + 注释 + ledger + `rank_broll_candidates` 的写法（可复用其 `_narration_segments` 思路）；`target_sec = audio_tts.media_info.duration_sec`；调 `plan_coverage(...)`。若 `not plan.sufficient` → `raise NodeExecutionError(ErrorCode.material_insufficient_broll, "B_roll material insufficient to cover the full narration duration.")`（**硬失败**，不发 degradation）。否则把 `CoverageSegment` 映射成 `BrollPlanArtifact` 的 segments + `BrollOverlay`（沿用既有字段）。

- [ ] **Step 1（test first）**：`tests/production/test_broll_coverage_planning.py`：构造内存 ctx（参考 `tests/production` 既有节点测试夹具）。① 充足素材 → 产 `plan_broll`，segments 覆盖至 `audio_tts` 时长。② 素材不足 → `NodeExecutionError(material_insufficient_broll)`。
- [ ] **Step 2**：跑 → 失败。
- [ ] **Step 3**：实现节点。
- [ ] **Step 4**：测试绿。
- [ ] **Step 5**：交回 Claude 提交。

> 注：若 `ErrorCode.material_insufficient_broll` 不存在，复用 `tests` 现有 broll 不足相关 ErrorCode/WarningCode（先 grep `material_insufficient` 确认枚举名），不要新造契约枚举除非确无可用项；若必须新增则同步 `contracts/base.py` + `__init__.py` 并在提交说明标注。

---

### Task 5: `BrollTimelinePlanning` 节点

**Files:**
- Create: `packages/production/pipeline/nodes/broll_timeline_planning.py`
- Test: `tests/production/test_broll_timeline_planning.py`（新增）

**Interfaces:**
- Consumes：`ctx.state.require(ArtifactKind.audio_tts)`（`media_info.duration_sec` → duration）、`ctx.state.require(ArtifactKind.plan_broll)`、`Task 1` 的 `_timeline_grid.{to_frame,build_tracks,validate_timeline}`、`ctx.state.request.output.{width,height,fps}`。
- Produces：`ArtifactKind.plan_timeline`（`"TimelinePlanArtifact.v1"`）+ `ArtifactKind.plan_render`（`"RenderPlanArtifact.v1"`）。

**行为**：`duration = audio_tts.media_info.duration_sec`（≤0 抛 `render_invalid_timeline`）；`fps = request.output.fps`；`total_frames = max(1, round(duration*fps))`。把 plan_broll 的 segments 组成**单一 `track_id="broll"` 的 base 轨**（raw_segments，时间轴帧由 `to_frame` 算），`build_tracks` + `validate_timeline`；若 `not validation.valid` → `render_invalid_timeline`（纵深防御）。产 `TimelinePlanArtifact(fps,total_frames,tracks,validation)` 与 `RenderPlanArtifact(render_size=(w,h),fps,tracks,timeline_artifact_id=<新建 plan_timeline id>)`，写法对齐 `timeline_planning.py:131-158`。

- [ ] **Step 1（test first）**：`tests/production/test_broll_timeline_planning.py`：给定 `audio_tts`(duration=D) + 铺满 `plan_broll` → `total_frames==round(D*fps)`，tracks 全为 `broll`，`validation.valid==True`，并产出 `plan_render`。
- [ ] **Step 2–4**：失败 → 实现 → 绿。
- [ ] **Step 5**：交回 Claude 提交。

---

### Task 6: `BrollRenderBase` 节点

**Files:**
- Create: `packages/production/pipeline/nodes/broll_render_base.py`
- Test: `tests/production/test_broll_render_base.py`（新增）

**Interfaces:**
- Consumes：`ctx.state.require(ArtifactKind.plan_render)`、`ctx.state.require(ArtifactKind.plan_timeline)`、`ctx.state.require(ArtifactKind.plan_broll)`、`render_broll_montage`、`ctx.source_artifact_for_asset`、`ctx.artifact_path`、`ctx.object_store()`、`store_file`。
- Produces：`ArtifactKind.video_rendered`（uri-only，`tier="ephemeral"`，附 `media_info`/`sha256`），写法对齐 `render_final_timeline.py:50-65`。

**行为**：取 `total_frames`/`render_size`/`fps`；`segments = plan_broll.segments`；调 `render_broll_montage(...)` 输出到临时文件 → `validate_rendered_output` → `store_file(..., purpose="generated-video", tier="ephemeral")` → `ctx.artifact(video_rendered, None, "uri-only", uri=..., sha256=..., media_info=...)`。ffmpeg 失败抛 `NodeExecutionError(exc.error_code, ...)`。

- [ ] **Step 1（test first）**：`tests/production/test_broll_render_base.py`：seed 媒体 + 铺满 plan → 产 `video_rendered`，`media_info` 帧数 == total_frames。
- [ ] **Step 2–4**：失败 → 实现 → 绿。
- [ ] **Step 5**：交回 Claude 提交。

---

### Task 7: 模板注册 + 序列 + handler + 节点计数 + ValidateRequest 扩展

**Files:**
- Modify: `packages/production/pipeline/node_sequence.py`（加 `BROLL_ONLY_SEQUENCE`、`WORKFLOW_TEMPLATE_NODE_COUNTS["broll_only_v1"]`）
- Modify: `packages/production/pipeline/digital_human.py`（`broll_only_template()` + `template_for()` 注册表 + `NODE_HANDLERS` 加 3 个新节点）
- Modify: `packages/production/pipeline/nodes/__init__.py`（导出 3 个新节点 run）
- Modify: `packages/production/pipeline/nodes/validate_request.py`（broll_only 下要求 `broll.enabled`）
- Test: `tests/production/test_broll_only_template.py`（新增）

**Interfaces — Produces（Task 8 依赖）:**
```python
# digital_human.py
def broll_only_template() -> WorkflowTemplate: ...   # workflow_template_id="broll_only_v1", version 与 digital_human 对齐风格
def template_for(workflow_template_id: str) -> WorkflowTemplate:
    """注册表分发：{"digital_human_v2": digital_human_template, "broll_only_v1": broll_only_template}；未知 id 抛 ValueError。"""
```
`BROLL_ONLY_SEQUENCE`（13）= ValidateRequest, LoadCaseContext, ResolveCreativeIntent, TTS, MaterialPackPlanning, NarrationAlignment, **BrollCoveragePlanning**, StylePlanning, **BrollTimelinePlanning**, **BrollRenderBase**, SubtitleAndBgmMix, ExportFinishedVideo, FinalizeRunReport。

**节点 id 命名**：`BrollCoveragePlanning` / `BrollTimelinePlanning` / `BrollRenderBase`（与 NODE_SEQUENCE 字符串、NODE_HANDLERS key 一致）。side_effects/idempotency_key：新节点无 provider 副作用 → 不设 idempotency_key；TTS/ResolveCreativeIntent 仍带（沿用 digital_human_template 的设定）。

**ValidateRequest 扩展**：不要写 `if template_id==...`；改为**读 `request.broll.enabled`**——当为 False 且模板不含 portrait 链时无 B_roll 可铺会导致后续硬失败，故在 broll_only 模板下应校验 `broll.enabled`。实现方式：在 `ValidateRequest` 用「当前 run 的 `workflow_template_id`」判断是否 broll_only 模式（这是模板元数据驱动，可接受），或更解耦地：给模板/NodeSpec 加一个轻量 capability 标记。**首选**：`validate_request` 读 `state.run.workflow_template_id == "broll_only_v1"` 仅用于「要求 broll.enabled」这一条校验（单点、非业务编排分支）——在提交说明里标注这是唯一的模式感知点。

- [ ] **Step 1（test first）**：`tests/production/test_broll_only_template.py`：`broll_only_template().workflow_template_id=="broll_only_v1"`、`len(nodes)==13`、节点顺序 == `BROLL_ONLY_SEQUENCE`、不含 Portrait/PortraitTrackBuild/LipSync；`template_for("broll_only_v1")` 返回它，`template_for("digital_human_v2")` 仍返回 16 节点模板；`expected_node_count("broll_only_v1")==13`。
- [ ] **Step 2–4**：失败 → 实现 → 绿。
- [ ] **Step 5**：`pytest tests/production -q` 不回归。交回 Claude 提交。

---

### Task 8: 把模板选择接到 API + Temporal adapter（parity）

**Files:**
- Modify: `apps/api/services/jobs_runs.py:98`（`digital_human_template()` → `template_for(request.workflow_template_id)`）
- Modify: `packages/core/workflow/temporal_adapter.py`（`_template_from_run` / `_workflow_payload` 经 `template_for` 重建）
- Test: `tests/workflow/test_broll_only_parity.py`（新增，对齐既有 parity guard 风格）；回归 `tests/workflow`

**行为**：所有「构造 template」的点统一走 `template_for(id)`；temporal parity 断言（重建模板 == 持久化的 `workflow_template_id`/version）对 `broll_only_v1` 成立。先 grep `digital_human_template(` 找全所有调用点改成注册表。

- [ ] **Step 1（test first）**：`tests/workflow/test_broll_only_parity.py`：用 `workflow_template_id="broll_only_v1"` 的 run，`_template_from_run` 重建出 13 节点模板且通过 parity 断言；跨模板（拿 digital_human_v2 的 run 期望 broll_only 模板）应失败。
- [ ] **Step 2–4**：失败 → 实现 → 绿。
- [ ] **Step 5**：`pytest tests/workflow tests/contract -q` 不回归。交回 Claude 提交。

---

### Task 9: `broll_only_v1` 端到端工作流测试

**Files:**
- Test: `tests/workflow/test_broll_only_run.py`（新增）

**行为**：用 memory backend + sandbox fallback 跑一个 `workflow_template_id="broll_only_v1"` 的完整 run（参考 `tests/workflow` 既有 digital_human 端到端测试夹具），断言：① 终态 succeeded/degraded；② 产出 `video_finished`；③ **未创建** `plan_portrait`/`video_portrait_track`/`video_lipsync` artifact（确认 A_roll 真被跳过）；④ 模板内 resume：复用前缀 + 从某节点 rerun 成功。

- [ ] **Step 1**：写端到端测试。
- [ ] **Step 2**：跑 → 视实现情况调试至绿（这是集成关，可能暴露前序任务的接缝问题——记录并回修对应任务）。
- [ ] **Step 3**：交回 Claude 提交。

---

### Task 10: Web 模式开关

**Files:**
- Modify: `apps/web/src/pages/studio/StudioCreatePage.tsx`（模式 Tab/Select：「数字人口播」/「仅B_roll画外音」；选后半者隐藏 portrait/lipsync 控件，`buildJobPayload` 发 `workflow_template_id="broll_only_v1"`）
- 视情况：`apps/web/src/pages/studio/*` 相关子组件
- Test: 前端按既有测试惯例（若有）；否则 `npm run build` 通过 + 手测路径说明

**行为**：默认 `digital_human_v2`；切到仅 B_roll 时，portrait/lipsync 相关字段不发或发默认值（后端忽略）。不动 `schema.d.ts`（契约未变）。

- [ ] **Step 1**：加模式状态 + 条件渲染 + payload 注入。
- [ ] **Step 2**：`cd apps/web && npm run build` 通过；`npm run lint`（若配置）通过。
- [ ] **Step 3**：交回 Claude 提交。

---

## 提交分组（Claude 执行，每任务一提交）

每个任务 Claude 单独 commit，消息形如：
- `refactor(timeline): extract frame-grid helpers shared by both timeline planners`
- `feat(planning): plan_coverage — deterministic full-duration B_roll selection`
- `feat(media): render_broll_montage — tile B_roll to fill the timeline`
- `feat(pipeline): BrollCoveragePlanning / BrollTimelinePlanning / BrollRenderBase nodes`
- `feat(pipeline): register broll_only_v1 template + template_for registry`
- `feat(api,workflow): select workflow template by id; broll_only_v1 parity`
- `test(workflow): broll_only_v1 end-to-end + resume`
- `feat(web): broll-only mode toggle on StudioCreatePage`

末尾统一带：
```
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

## Self-review（计划 vs spec 覆盖）

- spec §3 节点序列 → Task 7（BROLL_ONLY_SEQUENCE）✔
- spec §5.1 plan_coverage → Task 2 ✔；§5.2 render_broll_montage → Task 3 ✔；§5.3 三节点 → Task 4/5/6 ✔
- spec §6 接线/契约 → Task 7（模板/校验）+ Task 8（API/temporal）✔
- spec §7 重构 → Task 1 ✔
- spec §8 错误处理 → Task 4（硬失败）+ Task 5（纵深校验）+ Task 6（ffmpeg 失败）✔
- spec §9 Web → Task 10 ✔
- spec §10 测试 → 各任务 test-first + Task 9 端到端 + CI gate（验收阶段）✔
- spec §11 reuse/parity → Task 8 + Task 9 resume ✔
- spec §12 解耦自检 → 验收阶段逐项核对（Claude）

类型一致性：`plan_coverage`→`CoveragePlan/CoverageSegment`（Task 2）被 Task 4 消费；`_timeline_grid.{to_frame,build_tracks,validate_timeline}`（Task 1）被 Task 5 消费；`render_broll_montage`（Task 3）被 Task 6 消费；`template_for`（Task 7）被 Task 8 消费——签名前后一致。
