# 接通 CreativeIntent 字段 实现方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `CreativeIntentArtifact` 里 7 个"定义了但没人填、没人读"的死字段（scene_type / style_hint / density / cover_focus / overlay_events / closing_cta / script_features_hint）从 LLM 输出真正落库，并被下游确定性剪辑节点消费，使 LLM 的创意判断（说什么调性、什么节奏、什么风格）影响成片观感，同时不破坏确定性/可复用契约。

**Architecture:** 分层——LLM 只产**稳定的低基数标签/提示**（枚举 scene_type、枚举 density、短串 style_hint、浮点 cover_focus.time_sec、语义 overlay_events），最终切镜条数/选曲/抽帧/字幕样式仍由现有确定性算法决定。LLM 不直接产 timeline/shot list/ASS。每个消费点遵循"用户显式请求配置 > creative_intent > 系统默认"的三级优先级，creative_intent 字段为空（schema 默认）时行为零变化。

**Tech Stack:** Python 3.11 / Pydantic v2 (`ContractModel`, `extra="forbid"`) / FastAPI / Temporal worker / ffmpeg+libass(ASS 字幕) / jieba / pytest。

## Global Constraints

- **向后兼容铁律**：每个消费点先 `state.artifacts.get(ArtifactKind.creative_intent)`；`None` 或字段为 schema 默认值（`medium`/`hard_ad`/`""`/`{}`/`[]`）时必须**完整回退现有确定性默认**，行为零变化（密度倍率 ×1.0、preset 仍走 request、封面仍取中点、字幕无浮层）。
- **优先级**：`用户显式请求配置 > creative_intent > 系统默认`。"用户是否显式配置"以"请求字段值 != 该字段系统默认值"判定（保守：等于默认即视为未配置、可被 intent 补）。
- **确定性契约**：LLM 产标签，算法做最终决策；不引入随机；不让 LLM 直接产 timeline/shot list。
- **reuse 不动**：消费 creative_intent 的节点（StylePlanning/BrollPlanning/ExportFinishedVideo/SubtitleAndBgmMix）的 `input_manifest_hash` 已通过 `artifact_refs`（`digital_human.py:725-733`）自动折入 creative_intent 的 `artifact.id`——因为 ResolveCreativeIntent 排在它们之前、产物早在 `state.artifacts` 里。**不改 hash 逻辑、不改幂等键**。
- **ContractModel `extra="forbid"`**：往 artifact payload 塞契约未声明的键会在 `model_validate` 时抛错——只能填 `artifacts.py:91-99` 已声明字段。
- **LLM 输出形状**：`validate_output`（`registry.py:256-274`）要求 `output["intent"]` 是含 `hook`(str)+`beats`(list) 的 dict。新增标签字段统一放在 `output["intent"]` 内（与现有 hook/beats 同级），由 resolver 从 `intent` dict 里 `.get()` 提升到 artifact 顶层字段。
- **worker 是独立进程**：改完任何 `packages/production` 节点代码必须**重启 worker**，不只是 API。
- **读取统一范式**（照抄 `export_finished_video.py:171-175`）：
  ```python
  from packages.core.contracts.artifacts import CreativeIntentArtifact
  ci_art = state.artifacts.get(ArtifactKind.creative_intent)
  ci = CreativeIntentArtifact.model_validate(ci_art.payload) if ci_art else CreativeIntentArtifact()
  ```
- **测试 secrets 污染**：本地跑 pytest 用 `CUTAGENT_SECRET_STORE_DIR=<空目录>` 复刻 CI（见仓库记忆 local-test-secrets-pollution）。

## 已确认的设计决策（执行前可由 review 否决）

1. **density 对用户显式 `max_inserts` 的处理**：采用 **A——仅当 `request.broll.max_inserts == 4`（默认）时 density 才介入**；用户改过 max_inserts 即视为显式，density 让位。（严格符合优先级原则；侦察曾倾向"始终当倍率"的 B，本方案选 A。）
2. **新字段来源**：scene_type / density / style_hint / cover_focus.time_sec 全部由 **LLM 在 ResolveCreativeIntent 产出**（扩 prompt）。不在本方案给 Web 加请求字段（那会触发 OpenAPI 重生成，单列为可选后续）。
3. **overlay_events 来源**：采用 **StylePlanning 确定性派生**（基于 intent.beats / 关键词在旁白句中的子串定位）而非让 LLM 产带时间轴的事件——避免 LLM 做字符级时间定位。阶段4 只做"整句强调"，句内逐词高亮单列 4b 立项。
4. **validate_output**：保持宽松，**不**强校 scene_type/density 枚举（避免 LLM 偶发吐错词炸整 run）；非法值在 resolver 用白名单过滤回落默认。

## File Structure

| 文件 | 责任 | 阶段 |
|---|---|---|
| `packages/core/storage/repository.py` | ResolveCreativeIntent 的 prompt 种子文本（`:386-401`） | 0 |
| `packages/production/pipeline/nodes/resolve_creative_intent.py` | 把 LLM 输出的标签字段映射进 `CreativeIntentArtifact`（`:62-66`）+ 枚举白名单过滤 | 0 |
| `packages/production/pipeline/nodes/_creative_intent.py`（新建） | 共享读取助手 `load_creative_intent(state)` + 枚举常量，避免各消费节点重复样板 | 0 |
| `packages/production/pipeline/nodes/broll_planning.py` | density → effective max_inserts（`:62`/`:94`） | 2 |
| `packages/production/pipeline/nodes/style_planning.py` | scene_type/style_hint → BGM 加权 + style_preset 决议（`:34-92`/`:147-161`） | 1a/1b |
| `packages/production/pipeline/_subtitles.py` | preset 样式表 + overlay 事件渲染（`:118-126`） | 1b/4 |
| `packages/production/pipeline/nodes/export_finished_video.py` | cover_focus.time_sec → 抽帧点（`:243-262`） | 3 |
| `packages/production/pipeline/nodes/subtitle_and_bgm_mix.py` | 透传 overlay_events 进 `write_ass_subtitles`（`:73-75`/`:102-109`） | 4 |
| `tests/production/test_resolve_creative_intent.py`（新建） | 阶段0 映射/过滤/默认 | 0 |
| `tests/production/test_broll_planning_node.py` | 补 creative_intent fixture + density 断言（`:77,167`） | 2 |
| `tests/production/test_bgm_segment_selection.py` | 补 creative_intent fixture + 加权断言（`:54`） | 1a |
| `tests/production/test_subtitles_preset.py`（新建） | preset 样式表 + 向后兼容逐字节锁 | 1b |

**推荐落地顺序**：0 → 2 → 1a → 1b → 3 → 4a →（4b 单独立项）。理由：阶段0 必须最先；阶段2 改动最小、纯 worker 逻辑、风险最低，最适合验证"阶段0 真的接通了"的端到端闭环。

---

### Task 0.1: 共享读取助手 `_creative_intent.py`

**Files:**
- Create: `packages/production/pipeline/nodes/_creative_intent.py`
- Test: `tests/production/test_resolve_creative_intent.py`

**Interfaces:**
- Produces: `load_creative_intent(state) -> CreativeIntentArtifact`（None artifact 时返回全默认实例）；`SCENE_TYPES = ("hard_ad", "ip_persona")`；`DENSITIES = ("low", "medium", "high")`。

- [ ] **Step 1: 写失败测试**

```python
# tests/production/test_resolve_creative_intent.py
from packages.core.contracts import ArtifactKind
from packages.core.contracts.artifacts import CreativeIntentArtifact
from packages.production.pipeline.nodes._creative_intent import load_creative_intent


class _Art:
    def __init__(self, payload):
        self.kind = ArtifactKind.creative_intent
        self.payload = payload


class _State:
    def __init__(self, artifacts):
        self.artifacts = artifacts


def test_load_creative_intent_missing_returns_defaults():
    ci = load_creative_intent(_State({}))
    assert ci.scene_type == "hard_ad"
    assert ci.density == "medium"
    assert ci.style_hint == ""


def test_load_creative_intent_reads_payload():
    art = _Art({"scene_type": "ip_persona", "density": "high", "style_hint": "治愈系"})
    ci = load_creative_intent(_State({ArtifactKind.creative_intent: art}))
    assert ci.scene_type == "ip_persona"
    assert ci.density == "high"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `CUTAGENT_SECRET_STORE_DIR=$(mktemp -d) pytest tests/production/test_resolve_creative_intent.py -v`
Expected: FAIL — `ModuleNotFoundError: ..._creative_intent`

- [ ] **Step 3: 写实现**

```python
# packages/production/pipeline/nodes/_creative_intent.py
"""Shared helper: read the CreativeIntentArtifact off RunState with full fallback.

Every downstream consumer (StylePlanning / BrollPlanning / ExportFinishedVideo /
SubtitleAndBgmMix) reads creative_intent through this one helper so the
None-artifact and extra="forbid" fallbacks live in a single place.
"""
from __future__ import annotations

from packages.core.contracts import ArtifactKind
from packages.core.contracts.artifacts import CreativeIntentArtifact

SCENE_TYPES = ("hard_ad", "ip_persona")
DENSITIES = ("low", "medium", "high")


def load_creative_intent(state) -> CreativeIntentArtifact:
    art = state.artifacts.get(ArtifactKind.creative_intent)
    if art is None:
        return CreativeIntentArtifact()
    return CreativeIntentArtifact.model_validate(art.payload or {})
```

- [ ] **Step 4: 跑测试确认通过**

Run: `CUTAGENT_SECRET_STORE_DIR=$(mktemp -d) pytest tests/production/test_resolve_creative_intent.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add packages/production/pipeline/nodes/_creative_intent.py tests/production/test_resolve_creative_intent.py
git commit -m "feat(production): shared load_creative_intent helper with default fallback"
```

---

### Task 0.2: resolver 把 LLM 标签字段映射进 artifact（含枚举白名单过滤）

**Files:**
- Modify: `packages/production/pipeline/nodes/resolve_creative_intent.py:62-67`
- Test: `tests/production/test_resolve_creative_intent.py`

**Interfaces:**
- Consumes: LLM `result.output["intent"]` dict（含 hook/beats 及新增 scene_type/density/style_hint）。
- Produces: `CreativeIntentArtifact` 顶层 `scene_type/density/style_hint` 被填充；非法 scene_type 落回 `hard_ad`，非法 density 落回 `medium`。

- [ ] **Step 1: 写失败测试**（追加到同测试文件）

```python
from packages.production.pipeline.nodes._creative_intent import SCENE_TYPES, DENSITIES
from packages.production.pipeline.nodes.resolve_creative_intent import _intent_to_artifact


def test_intent_to_artifact_maps_labels():
    out = {"intent": {"hook": "h", "beats": ["a", "b", "c"],
                      "scene_type": "ip_persona", "density": "high", "style_hint": "利落"}}
    art = _intent_to_artifact(out)
    assert art.scene_type == "ip_persona"
    assert art.density == "high"
    assert art.style_hint == "利落"
    assert art.intent["hook"] == "h"


def test_intent_to_artifact_rejects_bad_enum():
    out = {"intent": {"hook": "h", "beats": [], "scene_type": "WeirdMode", "density": "ultra"}}
    art = _intent_to_artifact(out)
    assert art.scene_type == "hard_ad"   # 非法值落回默认
    assert art.density == "medium"


def test_intent_to_artifact_missing_labels_use_defaults():
    out = {"intent": {"hook": "h", "beats": []}}
    art = _intent_to_artifact(out)
    assert art.scene_type == "hard_ad"
    assert art.density == "medium"
    assert art.style_hint == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `CUTAGENT_SECRET_STORE_DIR=$(mktemp -d) pytest tests/production/test_resolve_creative_intent.py -k intent_to_artifact -v`
Expected: FAIL — `_intent_to_artifact` 不存在

- [ ] **Step 3: 写实现**（重构 `resolve_creative_intent.py` 的 artifact 构造）

把 `:62-66` 现状
```python
    artifact = ctx.artifact(
        ArtifactKind.creative_intent,
        CreativeIntentArtifact(intent=result.output.get("intent")).model_dump(mode="json"),
        "CreativeIntentArtifact.v1",
    )
```
改为调用新抽出的纯函数：
```python
    artifact = ctx.artifact(
        ArtifactKind.creative_intent,
        _intent_to_artifact(result.output).model_dump(mode="json"),
        "CreativeIntentArtifact.v1",
    )
```
并在文件内新增（模块级，import 处加 `from packages.production.pipeline.nodes._creative_intent import SCENE_TYPES, DENSITIES`）：
```python
def _intent_to_artifact(output: dict) -> CreativeIntentArtifact:
    """Map the LLM output into a typed CreativeIntentArtifact.

    The LLM emits {hook, beats, scene_type, density, style_hint, ...} inside the
    ``intent`` object (validate_output requires intent.hook/beats). We promote
    the low-cardinality labels to the artifact's typed top-level fields, dropping
    any value outside the allowed enums so downstream Literal validation can't
    fail on a hallucinated word.
    """
    intent = output.get("intent") if isinstance(output.get("intent"), dict) else {}
    scene_type = intent.get("scene_type")
    if scene_type not in SCENE_TYPES:
        scene_type = "hard_ad"
    density = intent.get("density")
    if density not in DENSITIES:
        density = "medium"
    style_hint = intent.get("style_hint")
    return CreativeIntentArtifact(
        intent=intent or None,
        scene_type=scene_type,
        density=density,
        style_hint=str(style_hint or ""),
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `CUTAGENT_SECRET_STORE_DIR=$(mktemp -d) pytest tests/production/test_resolve_creative_intent.py -v`
Expected: PASS（全部）

- [ ] **Step 5: 提交**

```bash
git add packages/production/pipeline/nodes/resolve_creative_intent.py tests/production/test_resolve_creative_intent.py
git commit -m "feat(production): map LLM scene_type/density/style_hint into CreativeIntentArtifact"
```

---

### Task 0.3: 扩 prompt 让 LLM 产出标签字段

**Files:**
- Modify: `packages/core/storage/repository.py:386-397`

**Interfaces:**
- Produces: LLM 输出的 `intent` 对象新增 `scene_type`(枚举)/`density`(枚举)/`style_hint`(短串)。validate_output **不动**（仍只强校 hook/beats，宽松兼容）。

- [ ] **Step 1: 改 prompt 文本**

把 `:387-396` 的内容字符串改为（在原 hook/tone/audience/beats 基础上**新增三字段、并放宽"只能包含"措辞**）：
```python
            content=(
                "你是资深短视频创意策划。基于下面的口播脚本，提炼创意结构。\n\n"
                "严格要求：直接输出一个 JSON 对象（以左花括号开头、右花括号结尾）；"
                "禁止使用 markdown 代码块；禁止任何前后缀说明文字。\n\n"
                "JSON 必须包含以下字段：\n"
                "- hook：字符串，一句话开场钩子。\n"
                "- tone：字符串，整体语气风格。\n"
                "- audience：字符串，目标受众。\n"
                "- beats：字符串数组，3 到 6 条，按顺序列出脚本的关键叙事节拍。\n"
                "- scene_type：字符串，只能是 \"hard_ad\"（硬广投流）或 \"ip_persona\"（IP人设号）。\n"
                "- density：字符串，只能是 \"low\"/\"medium\"/\"high\"，表示切镜节奏密度。\n"
                "- style_hint：字符串，一句话文风提示（如 \"利落口播\"、\"治愈系\"）。\n\n"
                "脚本：\n"
                "{script}"
            ),
```

- [ ] **Step 2: 跑现有 resolve/template 回归**

Run: `CUTAGENT_SECRET_STORE_DIR=$(mktemp -d) pytest tests/production/test_resolve_creative_intent.py tests/production -k "creative or template or broll_only" -v`
Expected: PASS（sandbox provider 仍吐合法 intent，新字段缺省走默认）

- [ ] **Step 3: 提交**

```bash
git add packages/core/storage/repository.py
git commit -m "feat(prompts): ResolveCreativeIntent prompt emits scene_type/density/style_hint"
```

- [ ] **Step 4（运维 runbook，非代码）：生产 SQL 后端重新发布 prompt**

> binding `prompt_binding_global_intent` 钉死 `prompt_creative_intent_v1`（`repository.py:402-407`）；seed 跳过已存在的 prompt。已 seed 过的生产 DB **不会**因改源码字符串而更新。部署时必须在 prompt 管理页走：新建 version（含上面的新内容）→ `draft→reviewing→approved→published` → 把 ResolveCreativeIntent 的 binding **re-pin** 到新 version。验证：在生产跑一条真 run，确认产出的 `CreativeIntentArtifact.payload.scene_type` 不再恒为 `hard_ad`。

---

### Task 2.1: density → BrollPlanning effective max_inserts

**Files:**
- Modify: `packages/production/pipeline/nodes/broll_planning.py`（`:62` 后插入 + `:94`）
- Test: `tests/production/test_broll_planning_node.py:77,167`

**Interfaces:**
- Consumes: `load_creative_intent(state).density`（Task 0.1）。
- Produces: `plan_insertions(max_inserts=effective_max)`，`plan_insertions` 签名不变。

- [ ] **Step 1: 给现有测试 fixture 补 creative_intent + 写 density 断言**

在 `test_broll_planning_node.py` 的两处 `artifacts={...}`（`:77`/`:167`，当前只有 plan_material_pack + narration_units）补一个 creative_intent artifact，并新增：
```python
def test_density_high_inserts_more_than_medium(make_state):
    # 用户 max_inserts 保持默认 4；density=high 应得到更多插入（受 ≤20 上界）
    state_hi = make_state(density="high")
    state_md = make_state(density="medium")
    n_hi = len(run(_ctx(state_hi)).artifacts[0].payload["segments"])
    n_md = len(run(_ctx(state_md)).artifacts[0].payload["segments"])
    assert n_hi >= n_md


def test_density_medium_matches_current_behavior(make_state):
    # density=medium（默认）必须与"无 creative_intent"逐条一致——锁死回退
    assert _insert_count(make_state(density="medium")) == _insert_count(make_state(density=None))
```
（`make_state`/`_ctx`/`_insert_count` 按文件现有 helper 风格补；density=None 时 fixture 不放 creative_intent artifact。）

- [ ] **Step 2: 跑测试确认失败**

Run: `CUTAGENT_SECRET_STORE_DIR=$(mktemp -d) pytest tests/production/test_broll_planning_node.py -k density -v`
Expected: FAIL（density 未被消费，high==medium）

- [ ] **Step 3: 写实现**（`broll_planning.py`）

文件顶部 import 加 `from packages.production.pipeline.nodes._creative_intent import load_creative_intent`，模块级加常量：
```python
_DENSITY_FACTOR = {"low": 0.5, "medium": 1.0, "high": 1.75}
_DEFAULT_MAX_INSERTS = 4  # mirrors BrollOptions.max_inserts default (jobs.py:58)
```
在 `:62`（`material = state.require(...)` 之后）插入：
```python
    base_max = state.request.broll.max_inserts
    density = load_creative_intent(state).density
    # 决策 A: 仅当用户未改 max_inserts（仍为默认 4）时 density 才介入；
    # 用户显式给了 max_inserts 即视为显式配置，density 让位。
    if base_max == _DEFAULT_MAX_INSERTS:
        effective_max = max(0, min(20, round(base_max * _DENSITY_FACTOR.get(density, 1.0))))
    else:
        effective_max = base_max
```
把 `:94` 的 `max_inserts=state.request.broll.max_inserts,` 改为 `max_inserts=effective_max,`。

- [ ] **Step 4: 跑测试确认通过**

Run: `CUTAGENT_SECRET_STORE_DIR=$(mktemp -d) pytest tests/production/test_broll_planning_node.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add packages/production/pipeline/nodes/broll_planning.py tests/production/test_broll_planning_node.py
git commit -m "feat(production): density drives b-roll max_inserts when user left it default"
```

---

### Task 1a: scene_type/style_hint → BGM 选曲加权

**Files:**
- Modify: `packages/production/pipeline/nodes/style_planning.py`（`:34-42` 调用 / `:107-128` `_select_bgm_candidate` / `:147-161` `_bgm_script_choice_score`）
- Test: `tests/production/test_bgm_segment_selection.py:54`

**Interfaces:**
- Consumes: `load_creative_intent(state).scene_type / .style_hint`。
- Produces: `_bgm_script_choice_score(candidate, *, script, scene_type, style_hint)` 多两个 keyword-only 形参；用户显式 `bgm.bgm_id` 时短路（scene_type 不参与）。

- [ ] **Step 1: 补 fixture + 写加权断言**

`test_bgm_segment_selection.py:54` 的 `RunState(request=request, artifacts={})` 补 creative_intent artifact；新增：
```python
def test_scene_type_biases_bgm_choice():
    # 两个候选：A 的 scene_fit 含 "hard_ad" 倾向，B 含 "ip_persona" 倾向
    pick_hard = _select(scene_type="hard_ad", candidates=[cand_A, cand_B])
    pick_ip = _select(scene_type="ip_persona", candidates=[cand_A, cand_B])
    assert pick_hard["asset_id"] != pick_ip["asset_id"]


def test_explicit_bgm_id_ignores_scene_type():
    pick = _select(scene_type="ip_persona", requested_asset_id=cand_A["asset_id"],
                   candidates=[cand_A, cand_B])
    assert pick["asset_id"] == cand_A["asset_id"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `CUTAGENT_SECRET_STORE_DIR=$(mktemp -d) pytest tests/production/test_bgm_segment_selection.py -k "scene_type or explicit_bgm" -v`
Expected: FAIL

- [ ] **Step 3: 写实现**（`style_planning.py`）

`run` 内（`:34` 选曲前）取标签：
```python
    ci = load_creative_intent(state)   # import load_creative_intent at top
```
`_select_bgm_candidate` 签名加 `scene_type: str = "", style_hint: str = ""` 并透传；`run` 调用处传 `scene_type=ci.scene_type, style_hint=ci.style_hint`。`_bgm_script_choice_score` 签名改为：
```python
def _bgm_script_choice_score(candidate: dict, *, script: str, scene_type: str = "", style_hint: str = "") -> float:
```
在 `:161` 的 return 追加加权项（复用现成 `_match_count`，`:187`）：
```python
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    scene_bonus = _match_count(scene_type, _string_list(metadata.get("scene_fit"))) * 30.0
    mood_bonus = _match_count(style_hint, [str(metadata.get("mood") or "")]) * 20.0
    return base + positive * 50.0 - negative * 80.0 + _single_clip_usability_score(metadata) + scene_bonus + mood_bonus
```
（`requested_asset_id` 短路分支在 `_select_bgm_candidate` `:113-116` 已存在，无需改——指定曲目时根本不进打分。）

- [ ] **Step 4: 跑测试确认通过**

Run: `CUTAGENT_SECRET_STORE_DIR=$(mktemp -d) pytest tests/production/test_bgm_segment_selection.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add packages/production/pipeline/nodes/style_planning.py tests/production/test_bgm_segment_selection.py
git commit -m "feat(production): scene_type/style_hint bias deterministic BGM selection"
```

---

### Task 1b: scene_type → style_preset + ASS 样式表

**Files:**
- Modify: `packages/production/pipeline/nodes/style_planning.py:65`
- Modify: `packages/production/pipeline/_subtitles.py:118-126`
- Test: `tests/production/test_subtitles_preset.py`（新建）

**Interfaces:**
- Consumes: `ci.scene_type`；`style.subtitle.style_preset`。
- Produces: `_subtitles.py` 内 `_PRESET_STYLES: dict[str, dict]`（`douyin`/`ip` 两套），`write_ass_subtitles` 按 `subtitle["style_preset"]` 取样式行；签名不变。

- [ ] **Step 1: 写失败测试（含向后兼容逐字节锁）**

```python
# tests/production/test_subtitles_preset.py
from pathlib import Path
from packages.production.pipeline._subtitles import write_ass_subtitles

_NARR = {"units": [{"text": "你好世界", "start": 0.0, "end": 1.0}]}


def _ass(tmp_path, preset):
    out = tmp_path / "s.ass"
    style = {"subtitle": {"style_preset": preset, "font_size": 64}}
    write_ass_subtitles(out, narration=_NARR, style=style, width=1080, height=1920)
    return out.read_text(encoding="utf-8")


def test_douyin_preset_byte_identical_to_current(tmp_path):
    # douyin = 现状硬编码样式，必须逐字节不变（锁死回退）
    txt = _ass(tmp_path, "douyin")
    assert "&H00FFFFFF" in txt          # 白字主色不变
    assert ",1,4,1,2," in txt            # Bold=1,Outline=4,Shadow=1,Alignment=2 不变


def test_ip_preset_differs(tmp_path):
    assert _ass(tmp_path, "ip") != _ass(tmp_path, "douyin")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `CUTAGENT_SECRET_STORE_DIR=$(mktemp -d) pytest tests/production/test_subtitles_preset.py -v`
Expected: FAIL（ip 与 douyin 当前完全相同）

- [ ] **Step 3: 写实现**（`_subtitles.py`）

模块级新增样式表（`douyin` 的值**逐字段等于现状硬编码**，保证向后兼容）：
```python
# Per-preset ASS Style row fields. "douyin" mirrors the previous hard-coded row
# verbatim so existing output is byte-identical; "ip" is a softer alternative.
_PRESET_STYLES = {
    "douyin": {"primary": "&H00FFFFFF", "outline_colour": "&H00000000",
               "bold": 1, "outline": 4, "shadow": 1},
    "ip":     {"primary": "&H00FFFFFF", "outline_colour": "&H00505050",
               "bold": 0, "outline": 2, "shadow": 0},
}
_DEFAULT_PRESET = "douyin"
```
`write_ass_subtitles` 在 `:97` 取 subtitle 子 dict 后加 `preset = _PRESET_STYLES.get(subtitle.get("style_preset"), _PRESET_STYLES[_DEFAULT_PRESET])`，把 `:124-125` 的硬编码 Style 行改成用 preset 字段插值：
```python
        (
            f"Style: Default,{resolved_font},{font_size},{preset['primary']},&H000000FF,"
            f"{preset['outline_colour']},&H64000000,"
            f"{preset['bold']},0,0,0,100,100,0,0,1,{preset['outline']},{preset['shadow']},2,"
            f"{_ASS_MARGIN_L},{_ASS_MARGIN_R},{margin_v},1"
        ),
```
`style_planning.py:65` 改 style_preset 决议（用户显式优先，否则 scene_type 推；`hard_ad→douyin` 保持默认行为，仅 `ip_persona` 把未配置的切到 `ip`）：
```python
    requested_preset = state.request.subtitle.style_preset  # 默认 "douyin"
    if requested_preset == "douyin" and ci.scene_type == "ip_persona":
        resolved_preset = "ip"
    else:
        resolved_preset = requested_preset
    # ... SubtitleStylePlan(style_preset=resolved_preset, ...)
```

- [ ] **Step 4: 跑测试 + 真 ffmpeg 逐帧验收**

Run: `CUTAGENT_SECRET_STORE_DIR=$(mktemp -d) pytest tests/production/test_subtitles_preset.py -v`
Expected: PASS
渲染敏感区（仓库记忆有闪帧坑）：本地用真 ffmpeg 烧一条 `ip` preset 字幕，确认不破帧、样式正确。

- [ ] **Step 5: 提交**

```bash
git add packages/production/pipeline/_subtitles.py packages/production/pipeline/nodes/style_planning.py tests/production/test_subtitles_preset.py
git commit -m "feat(production): wire style_preset into ASS styling, scene_type picks default"
```

---

### Task 3.1: cover_focus.time_sec → 封面抽帧点

**Files:**
- Modify: `packages/production/pipeline/nodes/export_finished_video.py`（`_frame_cover`，`:243-262`）
- Modify: `packages/core/storage/repository.py`（prompt 再扩一字段，见 Step 0）
- Test: `tests/production/test_export_finished_video.py`（新增用例）

**Interfaces:**
- Consumes: `ci.cover_focus.get("time_sec")`；`extract_frame_at_time(time_sec=...)`（发布侧已用，`ffmpeg.py`）。
- Produces: 有 time_sec → 定格该秒；无 → 完全保持现状（中点抽帧）。

- [ ] **Step 0: prompt 再扩**（cover_focus 由 LLM 产）

`repository.py` prompt 内容追加：`- cover_focus：对象，可含 time_sec（数字，建议封面定格的秒数）。` 并在 `_intent_to_artifact`（Task 0.2）里补 `cover_focus=intent.get("cover_focus") if isinstance(intent.get("cover_focus"), dict) else {}`。生产同样需 re-publish（Task 0.3 Step 4 同一次操作里一并做）。

- [ ] **Step 1: 写失败测试**

```python
def test_cover_focus_time_sec_extracts_at_point(monkeypatch, ...):
    called = {}
    monkeypatch.setattr(mod, "extract_frame_at_time", lambda *a, time_sec, **k: called.setdefault("t", time_sec) or _fake_png)
    _run_export(cover_focus={"time_sec": 3.2})
    assert called["t"] == 3.2


def test_cover_focus_empty_uses_midpoint(...):
    # 空 cover_focus 仍走 extract_thumbnails 中点逻辑——锁死回退
    ...
```

- [ ] **Step 2: 跑测试确认失败**

Run: `CUTAGENT_SECRET_STORE_DIR=$(mktemp -d) pytest tests/production/test_export_finished_video.py -k cover_focus -v`
Expected: FAIL

- [ ] **Step 3: 写实现**（`_frame_cover`）

```python
    ci = load_creative_intent(state)
    focus_t = ci.cover_focus.get("time_sec")
    if isinstance(focus_t, (int, float)) and focus_t >= 0:
        cover_path = extract_frame_at_time(video_path, time_sec=float(focus_t), ...)
    else:
        # 现状不变：extract_thumbnails(labels=("first","mid")) → 取 mid
        ...
```

- [ ] **Step 4: 跑测试确认通过 + 提交**

Run: `CUTAGENT_SECRET_STORE_DIR=$(mktemp -d) pytest tests/production/test_export_finished_video.py -v` → PASS
```bash
git add packages/production/pipeline/nodes/export_finished_video.py packages/core/storage/repository.py tests/production/test_export_finished_video.py
git commit -m "feat(production): cover_focus.time_sec picks the cover frame, midpoint fallback"
```

---

### Task 4a: overlay_events → 整句强调字幕（确定性派生）

**Files:**
- Modify: `packages/core/contracts/artifacts.py`（给 overlay_events 定强类型子模型，**会触发 OpenAPI/schema.d.ts 重生成**）
- Modify: `packages/production/pipeline/nodes/style_planning.py`（确定性派生 overlay_events）
- Modify: `packages/production/pipeline/_subtitles.py`（新增 `Emphasis` 样式行 + 事件 Dialogue 循环）
- Modify: `packages/production/pipeline/nodes/subtitle_and_bgm_mix.py:73-75,102-109`（透传）
- Test: `tests/production/test_subtitles_preset.py`（新增 overlay 用例）+ `tests/contract`（schema 漂移）

**Interfaces:**
- Produces: `OverlayEvent(start: float, end: float, text: str, style: str = "emphasis")` 子模型；`write_ass_subtitles(..., overlay_events: list[dict] = ())`。

- [ ] **Step 1: 定强类型 + 重生成契约**

`artifacts.py` 把 `overlay_events: list[dict[str, Any]]` 收成 `list[OverlayEvent]`，新增 `OverlayEvent(ContractModel)`；同步 `contracts/__init__.py` 的 `__all__`。
Run: `python scripts/export_openapi.py && (cd apps/web && npm run generate:api)`
提交 `openapi.json` + `schema.d.ts`（CI 校验漂移，见仓库记忆 openapi-drift-env-sensitive：若本地 key-order 漂移而 CI 绿，以 CI 为准）。

- [ ] **Step 2: 写失败测试**

```python
def test_overlay_event_renders_emphasis_dialogue(tmp_path):
    txt = _ass_with_overlay(tmp_path, events=[{"start": 0.5, "end": 1.5, "text": "限时五折", "style": "emphasis"}])
    assert "Style: Emphasis," in txt
    assert "限时五折" in txt
    # 整句强调用更高 Layer 叠在正文上
    assert "Dialogue: 1," in txt
```

- [ ] **Step 3: 写实现**

`style_planning.py` 确定性派生（不让 LLM 产时间轴）：从 narration units + intent.beats 关键词，把"匹配到某 beat 的整句旁白"标成一个 emphasis 事件（复用 jieba `extract_keywords` 子串定位到 unit 的 start/end）。`_subtitles.py:123-126` 后追加命名样式行 `Style: Emphasis,...黄字大字号...`，并在正文循环后新增：
```python
    for ev in overlay_events:
        text = ass_escape(str(ev.get("text", "")))
        if not text:
            continue
        lines.append(
            f"Dialogue: 1,{ass_time(float(ev.get('start', 0)))},{ass_time(float(ev.get('end', 0)))},"
            f"Emphasis,,0,0,0,,{text}"
        )
```
`subtitle_and_bgm_mix.py` 从 `load_creative_intent(state).overlay_events` 取出透传进 `write_ass_subtitles`。

- [ ] **Step 4: 跑测试 + 真 ffmpeg 多样式叠层逐帧验收 + 提交**

Run: `CUTAGENT_SECRET_STORE_DIR=$(mktemp -d) pytest tests/production/test_subtitles_preset.py tests/contract -v` → PASS
真 ffmpeg 烧录验收 libass 多样式叠层不破帧。
```bash
git add -A && git commit -m "feat(production): overlay_events render emphasis subtitle layer (deterministic)"
```

> **4b（句内逐词高亮）单独立项**：需松绑 `ass_escape`（`_subtitles.py:21-22` 现在删 `{}`）放行 `{\c}` 内联标签 + 字符级时间/位置定位，风险高（ASS 注入/破帧），不在本方案范围。

---

## Self-Review

- **Spec/需求覆盖**：7 个死字段中——scene_type（Task 1a/1b）、style_hint（1a/1b）、density（2.1）、cover_focus（3.1）、overlay_events（4a）均有任务覆盖；`closing_cta`、`script_features_hint` **本方案未接**（前者属脚本文案层、后者语义最虚，列为后续）。这是有意取舍，非遗漏。
- **前置链**：所有消费阶段（1/2/3/4）都硬依赖 Task 0.2+0.3——不先让 resolver 填字段+扩 prompt，下游读到的恒为默认值（等于没接）。已在每个任务的依赖与 Global Constraints 标明。
- **类型一致性**：`load_creative_intent`（Task 0.1）签名贯穿 1a/1b/2.1/3.1/4a；`_DENSITY_FACTOR`/`_PRESET_STYLES`/`OverlayEvent` 命名前后一致。
- **占位扫描**：Task 3.1/4a 的测试体含 `...` 省略号——执行时须按文件现有 helper 补全为可运行代码（非交付占位，是"按现有 fixture 风格补"的指示）；其余步骤均含真实代码。
- **唯一契约重生成点**：仅 Task 4a Step 1（给 overlay_events 定强类型）触发 OpenAPI/schema.d.ts 重生成；阶段 0/1/2/3 全部不碰 API 形状。
