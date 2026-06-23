# CreativeIntent 字段架构地基 + 强调字幕 + beat 语义封面 · 设计（spec）

> issue #52 的**本期收敛实现设计**。经一轮 12-agent 深度尽调（证据见 [`../plans/2026-06-23-creative-intent-wiring-comprehensive.md`](../plans/2026-06-23-creative-intent-wiring-comprehensive.md)）+ 一轮 brainstorming 拍板，**本期范围大幅收窄**：只做两个真功能 + 一次字段架构清理，为以后的"花字"和"封面"打地基。本 spec 已用户批准（2026-06-23）。

## Goal

1. **强调字幕**：把 LLM 标记的"该强调的叙事 beat"确定性派生成带时间轴的整句强调字幕浮层（**花字地基**）。
2. **beat 语义封面**：LLM 产"封面落在哪个 beat"，下游用真实旁白时间换算成定格帧；该帧既改进 `frame` 模式/兜底封面，也作为 PR#54 AI 封面的参考/条件图（**封面地基**）。
3. **CreativeIntent 字段架构理干净**：`CreativeIntentArtifact` 从 8 字段（1 活 7 死）收敛成 3 个强类型字段，删 5 个确认死字段，好扩展、不堆没用字段。

## 核心原则

**CreativeIntent 只存 LLM 的低基数语义判断；带时间轴的 render 结果由下游确定性节点派生。** 完全贴合 issue 自身"LLM 产稳定低基数标签、算法做最终决策/产时间轴"的分层。扩展靠给子模型加字段，不靠在顶层堆空字段。

## Tech Stack / 约束

- Python 3.11 / Pydantic v2（`ContractModel`, `extra="forbid"`）/ FastAPI / Temporal worker（独立进程，改 `packages/production` 须重启）/ ffmpeg+libass / jieba / pytest。
- 领域类型唯一来源 `packages/core/contracts`；新增子模型须同步 `contracts/__init__.py` 的 import + `__all__`。

## 已核实的承重事实（本设计的地基）

| 事实 | 证据 | 对设计的意义 |
|---|---|---|
| 所有相关 artifact 都不在 OpenAPI 面 | `CreativeIntentArtifact/StylePlanArtifact/SubtitleStylePlan/OverlayEvent` 程序化核对均不在 components/schemas（308 schema） | **本设计零阶段触发 schema.d.ts 重生成**；派生时间轴落 StylePlanArtifact 也免费 |
| 节点顺序 | `node_sequence.py`：ResolveCreativeIntent(14)→NarrationAlignment(17)→StylePlanning(20)→SubtitleAndBgmMix(25)→ExportFinishedVideo(26) | StylePlanning/Export 都在对齐之后 → 派生强调字幕/封面帧时**真实旁白时间轴已就绪** |
| reuse 真闸是 node_version | `reuse.py:79-80` node_version 比对；`:81-82` manifest 比对因 `expected_input_manifest_hashes` 两处调用都没填而恒被跳过 | 改产物形状/消费逻辑的节点**必须 bump node_version**，否则 resume 复用旧产物跳过新逻辑 |
| sandbox + 真 provider 都不产新字段 | `provider_gateway.py:129` sandbox 只产 hook/tone/audience/beats；`resolve_creative_intent.py:64` 只填 intent | 单测**不能靠 sandbox** 验新字段，须 stub provider |
| `extra="forbid"` + 删字段的迁移坑 | `ContractModel` 默认 forbid；老 run 的 creative_intent payload 带旧 `scene_type` | resume 老 run 时若用新模型 `model_validate` 旧 payload 会炸 → 须 bump **ResolveCreativeIntent** node_version 让它先重产新形状 |
| PR#54 AI 封面有参考路径 | `_generate_ai_cover(ctx, profile_id, copy)` + `_frame_cover`（export_finished_video.py）+ cover_template image-edit 条件图入口 | beat 帧可喂 AI 封面参考；**依赖 PR#54 先合** |
| cover 默认即将 frame→ai | `jobs.py:94` 本地仍 `frame`；PR#54 改默认 `ai`，无 image provider 时 frame 是诚实兜底 | beat 封面改进的是 frame 模式 + AI 不可用兜底 + AI 参考图 |

## 字段架构（核心地基）

`packages/core/contracts/artifacts.py`：

```python
class CoverFocus(ContractModel):
    """LLM 对封面定格点的低基数语义判断。
    beat_index: 封面应定格在第几个叙事 beat（0-based，索引进 intent.beats）；
    None = 无偏好，下游回退视频中点（向后兼容）。
    下游 Export 用 narration_units 把 beat→真实秒数；frame 模式取该帧，
    ai 模式（PR#54）把该帧作为 AI 封面参考/条件图（无上传 cover_template 时）。
    未来扩展位（本期不加）：cover_text / style。"""
    beat_index: int | None = None


class EmphasisHint(ContractModel):
    """LLM 标记哪个叙事 beat 值得整句强调（花字地基）。
    beat_index: 要强调的 beat（0-based，索引进 intent.beats）。
    下游 StylePlanning 把 beat→匹配旁白句→带时间轴的 OverlayEvent。
    未来扩展位（本期不加）：style("highlight"/"pop") / word_targets / animation。"""
    beat_index: int


class CreativeIntentArtifact(ContractModel):
    intent: dict[str, Any] | None = None              # 现状保留（hook/tone/audience/beats），本期不强类型化
    cover_focus: CoverFocus = Field(default_factory=CoverFocus)
    emphasis: list[EmphasisHint] = Field(default_factory=list)
```

**删除字段**：`scene_type`、`style_hint`、`density`、`closing_cta`、`script_features_hint`、旧 `overlay_events: list[dict[str, Any]]`（全部确认零消费、零测试断言）。

派生的带时间轴字幕事件放到 **StylePlanArtifact**（`packages/core/contracts/artifacts.py`，与现有 subtitle/bgm 同级）：

```python
class OverlayEvent(ContractModel):
    """确定性派生的带时间轴字幕浮层事件（整句强调）。"""
    start: float
    end: float
    text: str
    style: str = "emphasis"

class StylePlanArtifact(ContractModel):
    # ...现有字段...
    overlay_events: list[OverlayEvent] = Field(default_factory=list)
```

> 同步：`contracts/__init__.py` 的 import + `__all__` 新增 `CoverFocus`/`EmphasisHint`/`OverlayEvent`。删除字段后跑 `python scripts/export_openapi.py && (cd apps/web && npm run generate:api)`，`git diff --exit-code` 兜底确认零漂移（预期零，因 artifact 不在 API 面）。

## 数据流（语义 → 派生）

```
ResolveCreativeIntent(14)   LLM 产：cover_focus.beat_index + emphasis:[{beat_index}]（低基数 beat 序号）
        │                   resolver 从 result.output["intent"] 解析、白名单/范围校验、提升到 artifact 顶层
        ▼
NarrationAlignment(17)      产 narration_units（真实 start/end）
        │
        ▼
StylePlanning(20)           确定性派生：每个 emphasis.beat_index → intent.beats[i] 文本
        │                   → jieba/子串匹配到旁白句 → OverlayEvent(start,end,text,"emphasis")
        │                   → 写入 StylePlanArtifact.overlay_events
        ▼
SubtitleAndBgmMix(25)       读 StylePlanArtifact.overlay_events → 透传 write_ass_subtitles
        │                   → _subtitles.py 渲染 Emphasis 样式行 + Layer1 Dialogue
        ▼
ExportFinishedVideo(26)     cover_focus.beat_index → intent.beats[i] → 匹配旁白句 start
                            → extract_frame_at_time 取该帧（frame 模式 / AI 参考图）
```

## 功能 A：强调字幕（不依赖 PR#54，可先行）

- **prompt 扩**：让 LLM 在 `intent` 里多产 `emphasis`（要强调的 beat 序号数组，低基数）。走新 prompt 版本 → publish → re-pin binding（含灰度/一键回滚）。
- **resolver**：`_intent_to_artifact` 把 `emphasis` 解析成 `list[EmphasisHint]`，beat_index 越界/非整数 → 丢弃该项（不炸）。
- **StylePlanning 派生**：对每个 emphasis beat，取 `intent.beats[beat_index]` 文本，用现成 jieba 关键词/子串在 narration_units 里定位整句 → `OverlayEvent(start,end,text,style="emphasis")`。匹配不到 → 跳过并上报 `DegradationNotice`（不静默）。
- **_subtitles.py**：新增 `Emphasis` 命名样式行（黄字/大字号）+ 在正文 Dialogue 循环后追加 `Dialogue: 1,...,Emphasis,...` 叠层；`ass_escape` 照旧删 `{}`（不放行内联标签，逐词高亮留 4b）。
- **验收**：真 ffmpeg 多样式叠层逐帧验收不破帧（记忆 frame-exact-render）。
- **bump node_version**：StylePlanning、SubtitleAndBgmMix。

## 功能 B：beat 语义封面（依赖 PR#54 先合）

- **prompt 扩**：LLM 多产 `cover_focus.beat_index`（封面落在哪个 beat）。
- **resolver**：解析成 `CoverFocus`，越界/非整数 → `beat_index=None`。
- **Export `_frame_cover` 改**：`cover_focus.beat_index` → `intent.beats[i]` 文本 → 匹配旁白句 start → `extract_frame_at_time(time_sec=该秒)`；
  - 先把 `extract_thumbnails` 的 **HDR tonemap 分支补进 `extract_frame_at_time`**（否则 HDR 封面回归）；
  - 加**非黑帧/有内容兜底**，失败回退中点；
  - `beat_index=None` 或匹配不到 → 完全保持现状（中点），逐字节锁测向后兼容。
- **Export `_generate_ai_cover` 改**（PR#54 之上）：无上传 `cover_template` 时，把上面派生的 beat 帧作为 AI 封面 image-edit 参考/条件图传入。
- **上报**：封面落黑帧回退、匹配不到 beat → `DegradationNotice`。
- **bump node_version**：ExportFinishedVideo。
- **明确分工**：export 产默认/参考封面；发布侧 `frame_time_sec` 仍是运营覆盖入口（不重复造轮）。

## 向后兼容 / node_version / 迁移

- 改 `CreativeIntentArtifact` 形状 → **bump ResolveCreativeIntent node_version**：resume 老 run 会重产新形状，避免下游 `model_validate` 撞 `extra="forbid"` 的旧 `scene_type` 炸。代价：resume 老 run 从节点 14 起重跑（正确且可接受）。
- 消费节点 StylePlanning / SubtitleAndBgmMix / ExportFinishedVideo 各 bump node_version（reuse 真闸）。
- 所有新字段空（`beat_index=None` / `emphasis=[]` / `overlay_events=[]`）→ 行为零变化：中点封面、无强调浮层。逐字节/逐条锁测。

## 不在本期范围（已拍板移出）

- style_preset 死参数修复、style_hint→BGM 加权、density→max_inserts、用户 Web 覆盖入口 + BatchItemOverrides。
- 句内逐词高亮（4b：需松绑 ass_escape + 字符级定位，风险高）。
- `intent` 强类型化（保持现状 dict）。

## 测试 / 契约

- 单测用 **stub provider**（sandbox 恒吐默认，验不了 emphasis/cover_focus 真值）。
- 向后兼容锁测：无新字段时封面/字幕逐字节不变。
- 派生匹配/越界/黑帧路径都有用例 + 断言上报降级。
- 契约：新增 3 子模型同步 `__all__`；`export_openapi + generate:api` + `git diff --exit-code` 兜底（预期零漂移）。

## 落地顺序

1. **架构清理 + 强调字幕**（功能 A，不依赖 PR#54）：删 5 死字段 + 加 3 子模型 + resolver 解析 + StylePlanning 派生 + _subtitles 渲染 + node_version bump + 测试。
2. **PR#54 合并后** → **beat 语义封面**（功能 B）：Export `_frame_cover` + HDR tonemap + 非黑帧兜底 + `_generate_ai_cover` 参考图 + node_version bump + 测试。

## 开放风险

- emphasis/cover 的 beat→旁白句匹配质量依赖现有 jieba 匹配；匹配不到时诚实降级回退，不假装见效（每步过真机见效闸：真 run 确认 Emphasis 行真出现、封面真定格对的帧）。
- 功能 B 依赖 PR#54 的 AI 封面参考路径，PR#54 未合前只能做 frame 模式那半；按落地顺序 2 在 PR#54 合并后做。
