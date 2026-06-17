# Case Agent 重构：评分卡自进化（`case_rubric_v1`）设计

> Status: Draft (2026-06-17) · Author: 架构 = Claude
> 关联：`packages/creative/cases`（现自进化闭环）、`apps/api/services/case_agent*.py`、`packages/production` 成片流水线、`docs/树影_Cutagent_CleanSlate重写Spec_v3` §8.4 / §25.4–25.8
> 参考：[`XBuilderLAB/cheat-on-content`](https://github.com/XBuilderLAB/cheat-on-content) 的 Score → 盲预测 → Publish → 复盘 → 升级 校准闭环

## 0. 一句话

把案例的"记忆"从**一堆要人工逐条审批的 insight 文本**，重构成**一张每个案例自己的、可执行的评分卡（Case Rubric）**：它给脚本打分、出盲预测；用**成片/发布/表现里的人类选择作为奖励信号**自动校准权重；人工只在"评分卡要升版"时确认一次。学习全程对用户无感，"智能体" tab 退化为只读档案。

## 1. 目标与范围

### 目标
1. **大幅精简**：用户面对的概念从十几个（source binding / brief / agent run×3 goal / reflection / memory proposal / approve / knowledge / insight / pattern…）收敛到 **3 个**：评分卡、看好程度（盲预测）、复盘。
2. **少人工、不为 0**：日常 0 操作；唯一常规人工是"评分卡升版"的一次确认 + 删废片时可选的一键原因。
3. **无感学习**：学习只搭用户**本来就会做的动作**的便车（选稿、做成片、发布、删废片），不新增"为训练 AI 而做"的步骤。
4. **职责归位**：脚本生成只在**创作页**（唯一生产入口）；智能体不再独立生成内容，只做后台学习 + 只读展示。
5. **保留 cheat-on-content 内核**：盲测、复盘、升级（含防自欺 guardrail）原样保留，只是换成 DB + 服务端不变量实现。
6. **前期可用**：在没有任何发布指标时（冷启动）也能产生价值——给脚本打分排序、稳定风格。

### 非目标（本期不做）
- 真正的 ML 训练 / 向量检索：评分卡学习用**确定性纯函数**（加权拟合 + 重排校验），不引入训练框架，保持可单测、与 `evolution.py` 同风格。
- 跨 provider 审计（cheat-on-content 的 cross-model audit）：放 P2；P1 先用"历史重打分必须更准"这个客观门槛防自欺。
- 删除既有指标/反思的**数据模型与纯函数**：它们复用，只下线 UI 与人工审批入口。
- 改 `digital_human_v2` 成片流水线的任何既有节点行为（只在导出/发布的 service 层挂奖励信号采集）。

## 2. 架构原则（必须守住）

1. **学习是纯函数 + 确定性**：评分、盲预测、权重拟合、重排校验都在 `packages/creative/cases/rubric.py`（新）里，**不查 DB、不调 provider、不随机**，便于测试。沿用现有 `evolution.py` 的范式。
2. **奖励信号搭车既有动作**：在已有 service 副作用点（adopt / 成片导出 / 发布 / 指标导入 / 删片）各埋一行 `RewardSignal` 写入，**不新增用户动作**。
3. **盲测靠服务端不变量**：盲预测一旦写入即 immutable（`locked_at` 锁定），且必须早于任何指标回流——用 DB 字段 + service 守卫，而非 cheat-on-content 的本地文件 hook。
4. **contract-first**：所有新类型进 `packages/core/contracts`，同步 `__init__.py` 的 import + `__all__`，改完重生成 `openapi.json` + `schema.d.ts`。
5. **双后端对称**：service 每条路径都保留 `…_repository is not None`（SQLAlchemy）/ else 内存 `Repository` 两条分支，共享同一套 `rubric.py` 纯函数。
6. **下线而非删除**：反思/记忆提案/审批端点下线（前期不挂 UI），数据模型与纯函数保留，等 P2 决定是否彻底移除。

## 3. 从 cheat-on-content 借了什么（映射表）

| cheat-on-content | 本设计的对应物 |
|---|---|
| `rubric_notes.md`（评分公式，唯一真源，可进化） | `CaseRubric`（DB 行：维度 + 权重 + 版本） |
| 7 个维度从 25+ 样本拟合 | `RubricDimension[]`，维度来源复用 `CreativeFeatureVector` |
| 盲预测 `## 预测` 段写完即 immutable | `ScorePrediction`（`locked_at` 后不可改） |
| blind-channel（部分权重对盲打分子 agent 隐藏） | 盲打分时**不喂任何真实指标**，只喂脚本特征 |
| 校准池 `calibration_pool`（已复盘样本） | 已结算奖励的 `ScorePrediction` 集合 |
| 复盘 retro（T+3d，逐维度 delta） | 指标回流后算 预测分 vs 实际奖励 的偏差 |
| 升级 bump（重打分 + 验证门 + 跨模型审计 + 签字） | `RubricBumpProposal`：重打分 + 重排一致性门槛 + 一次人工确认（P2 加跨 provider） |
| `benchmark.md` 标杆账号（冷启动 seed） | 复用 `reference_extract` 的参考视频 + 已采用脚本 seed 初始权重 |
| session-start hook 报 buffer / 待复盘 | 进案例时只读卡片："待复盘 N 条""本案例评分卡 vX" |
| 阈值不可自己改（meta-bump 单独审批） | bump 阈值是 `Settings` 配置项，改它不走自动流程 |
| 人类动作（选稿、发布）= 真实信号 | `RewardSignal`（本设计的核心新增，见 §5） |

**关键差异**：cheat-on-content 靠"发布后表现"作唯一 ground truth；我们额外把**创作/成片/发布链路上的人类选择**也作为（分级、加权的）奖励信号，所以前期没指标也能学。

## 4. 核心概念与数据流

### 4.1 三个用户可见概念
- **评分卡（Case Rubric）**：这个案例"什么样的内容更可能成"的打分公式。后台资产，用户在智能体 tab 只读看到"vX + 各维度权重"。
- **看好程度（盲预测）**：创作页生成每版脚本时自动给出的预测（🔥最看好 / 👍还不错 / 一般 + 一句理由）。用户用它选稿。
- **复盘**：发布后有了数据，系统自动对账"当初看好的，实际如何"，并据此（在够样本时）提议升版。

### 4.2 信号强度阶梯（学习样本来源）
```
草稿          被采用        做成成片       发布          发布有数据
ScriptDraft → ScriptVersion → FinishedVideo → PublishRecord → PerformanceObservation
  弱·······················(花了成本=认可)·····················强（终极答案）
（量大噪音多，不直接学）                                    （进校准池，可驱动升版）
```
- 越往后，奖励**置信度**越高（复用 `compute_performance_score` 的置信门控思路）。
- **废片**（`FinishedVideo` 存在但 N 天内无 `published` 的 `PublishRecord`，或被 `delete_finished_video`）→ 负/低信号（见 §5.2）。

### 4.3 端到端数据流
```
① 创作页生成（唯一入口）
   generate_script_with_memory → 出 N 版 ScriptDraft
   └─ rubric.score(features, active_rubric) → 每版一个 ScorePrediction（盲，locked）
   └─ 前端按 composite 降序展示「看好程度」

② 选稿 / 生产 / 发布（用户的自然动作 → 奖励信号）
   adopt_draft        → RewardSignal(draft_adopted,   +)   + 同批未选 draft_pick(−)
   成片导出(Export)    → RewardSignal(video_produced,  ++)
   publish            → RewardSignal(published,        +++)
   delete/归档废片     → RewardSignal(video_discarded, −, 可带原因)

③ 指标回流（有数据后）
   import_metrics → PerformanceObservation → compute_performance_score
                  → RewardSignal(performance_scored, value=normalized_score, 置信门控)
                  → 结算对应 ScorePrediction（脱离盲态，进校准池）

④ 复盘 + 升级（自动 + 一次确认）
   rubric.evaluate_calibration(校准池) → 一致性低/连续偏差
       → rubric.fit_weights(校准池) 产新候选卡
       → 仅当新卡在校准池上重排一致性 > 旧卡，才生成 RubricBumpProposal(proposed)
       → 用户一次确认 accept → 新 CaseRubric active、旧版 superseded
                       reject → 维持旧卡

⑤ 召回 / 消费
   - 创作页生成时：active rubric 既打分，也作为软提示注入 prompt（"本案例偏好：强痛点开场 / 短CTA…"）
   - 生产流水线 LoadCaseContext：继续注入 active 记忆（用户手钉的硬约束）+ 评分卡摘要
```

## 5. 奖励信号设计（本设计的核心新增）

### 5.1 `RewardSignal`
学习的"训练标签"。每条记录"某个脚本因为某个人类动作获得了多少奖励"。

| 字段 | 说明 |
|---|---|
| `script_version_id` / `script_draft_id` | 奖励归属的脚本主体（统一映射到其 feature vector） |
| `source_kind` | `draft_adopted` / `draft_pick` / `video_produced` / `published` / `performance_scored` / `video_discarded` / `stale_unpublished` |
| `value` | 归一化奖励，见 §5.2 |
| `confidence` | 阶段越靠后越高；`performance_scored` 直接取 `PerformanceScore.confidence`（含 `excluded_reason` 门控） |
| `evidence_ref` | `finished_video_id` / `publish_record_id` / `observation_id` 等溯源 |
| `reason` | 仅 `video_discarded` 用：`script` / `visual` / `topic` / `no_time` |
| `occurred_at` | 事件时间 |

### 5.2 默认奖励塑形（值进 `Settings`，可调，**不在代码里散落魔数**）

| 动作 | source_kind | value | confidence | 采集点（service） |
|---|---|---|---|---|
| 采用草稿 | `draft_adopted` | +0.2 | 0.4 | `case_agent.adopt_script_draft` |
| 同批落选 | `draft_pick` | −0.05 | 0.3 | 同上（对未被 adopt 的同批 draft） |
| 做成成片 | `video_produced` | +0.4 | 0.6 | 成片落库（`finished_videos` / Export 节点后） |
| 发布 | `published` | +0.7 | 0.8 | `publishing` 发布成功 |
| 有表现 | `performance_scored` | `normalized_score`∈[0,1] | = `PerformanceScore.confidence` | `import_metrics` |
| 删/归档废片 | `video_discarded` | 原因=`script` → −0.3；其他 → 0（不算账） | 0.5 | `delete_finished_video` |
| 成片 N=30d 未发布 | `stale_unpublished` | −0.1 | 0.3 | 惰性：复盘/读取时按 `created_at` 算，不引定时任务 |

设计要点：
- **废片不是噪音**：用 `reason` 区分"脚本不行"（负样本）和"非脚本原因"（不算账），避免冤枉好脚本——这是"轻干预"的最佳落点。
- **置信门控**：`performance_scored` 直接继承 §25.6 的 `excluded_reason`（低曝光/早窗口不进校准池），杜绝拿播放量当质量。
- **同批 pairwise**：`draft_adopted` + 同批 `draft_pick` 构成"选了A没选B"的相对信号，**不依赖发布**，前期即可学。

## 6. 评分卡：打分 / 盲测 / 复盘 / 升级

全部在新纯函数模块 `packages/creative/cases/rubric.py`。

### 6.1 打分（score）
```
composite = Σ_d  weight[d] · feature_score[d]      # 加权和，归一到 [0,10]
band      = 最看好(≥7.5) / 还不错(≥5) / 一般(<5)    # 给用户的人话
reasons   = 取贡献最大的 1–2 维度生成一句中文理由
```
- `feature_score[d]`：把 `CreativeFeatureVector` 的维度（hook_type / script_structure / cta_type / cut_density / …）映射到 [0,1]（类目维度查"该取值的历史平均奖励表"，数值维度做区间归一）。
- 复用 `evolution.extract_script_features` / `extract_video_features` 产 feature vector。

### 6.2 盲测（blind prediction）
- 生成脚本时即产 `ScorePrediction(composite, band, locked_at=now)`，**只读脚本特征，绝不读任何真实指标**。
- `locked_at` 写入后 `composite`/维度分 **immutable**：service 层拒绝更新（对应 cheat-on-content 的 `prediction-immutability.sh`）。
- 不变量：任何 `performance_scored` 奖励必须满足 `observation.observed_at > prediction.locked_at`，否则视为污染、不结算。

### 6.3 复盘（retro）
- `evaluate_calibration(predictions, rewards)`：在**已结算**样本上算
  - 逐样本 `delta = actual_reward − predicted_norm`
  - 排序一致性：预测分排序 vs 实际奖励排序（用 top-k 命中率 / Kendall-τ）
  - 连续同向大 `delta` 计数（对应 cheat-on-content "连续 3 次误判"）
- 输出 `CalibrationReport`（只读展示在智能体 tab + 决定是否触发升级）。

### 6.4 升级（bump）—— 唯一常规人工
触发（全部满足）：
1. 校准池样本 ≥ `MIN_SAMPLES_FOR_BUMP`（默认 5）；
2. 排序一致性 < 阈值 `BUMP_CONSISTENCY_FLOOR`，或连续同向误判 ≥ `BUMP_MISS_STREAK`（默认 3）。

生成新候选卡：`fit_weights(校准池)` —— 确定性地按"各维度取值的奖励均值差"调权（高奖励维度升权、被反驳的降权/删除）。

**防自欺 guardrail（移植 cheat-on-content）**：
1. **全量重打分**：新权重必须重打**所有**校准池样本；
2. **验证门**：新卡重排一致性必须 **> 旧卡**，否则 `fit` 结果直接丢弃，不打扰用户；
3. **盲不可破**：只用 `locked_at` 早于指标的预测进池；
4. **阈值不可自动改**：`BUMP_*` 是 `Settings`，改它不在自动流程内；
5. **（P2）跨 provider 审计**：升版前用另一 provider 独立复核。

只有过了 1–4 的候选才落 `RubricBumpProposal(proposed)`，推给用户**一次确认**：
> "我发现你的号最近更吃『痛点开场』。按新方式帮你判断好吗？" [好的 / 先不用]

`accept` → 新 `CaseRubric` `active`、旧版 `superseded`；`reject` → 维持。

## 7. 新增契约（`packages/core/contracts/cases.py`，草案）

```python
class RubricDimension(ContractModel):
    key: str                       # 对齐 CreativeFeatureVector 字段名，如 "hook_type"
    label: str                     # 人话维度名："开场强度"
    weight: float = Field(ge=0, le=1)
    kind: Literal["categorical", "numeric"] = "categorical"
    # categorical: 取值→[0,1] 评分表；numeric: 归一区间
    value_scores: dict[str, float] = Field(default_factory=dict)
    numeric_range: tuple[float, float] | None = None

class CaseRubric(EntityMeta):
    case_id: str
    version: int = 1
    status: Literal["draft", "active", "superseded"] = "active"
    dimensions: list[RubricDimension] = Field(default_factory=list)
    fitted_from_sample_size: int = 0
    cold_start: bool = True        # 仍为行业默认/参考 seed，未经真实奖励校准
    supersedes_version: int | None = None

class ScorePrediction(EntityMeta):
    case_id: str
    script_draft_id: str | None = None
    script_version_id: str | None = None
    rubric_version: int
    composite: float = Field(ge=0, le=10)
    band: Literal["top", "ok", "low"]
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    reason: str = ""
    locked_at: datetime = Field(default_factory=utcnow)   # immutable 之后
    # 复盘结算（盲态结束后才写）
    settled_reward: float | None = None
    settled_at: datetime | None = None

class RewardSignal(EntityMeta):
    case_id: str
    script_version_id: str | None = None
    script_draft_id: str | None = None
    source_kind: Literal[
        "draft_adopted", "draft_pick", "video_produced",
        "published", "performance_scored", "video_discarded", "stale_unpublished",
    ]
    value: float
    confidence: float = Field(0.5, ge=0, le=1)
    evidence_ref: str | None = None
    reason: Literal["script", "visual", "topic", "no_time"] | None = None
    occurred_at: datetime = Field(default_factory=utcnow)

class RubricBumpProposal(EntityMeta):
    case_id: str
    status: Literal["proposed", "accepted", "rejected"] = "proposed"
    from_version: int
    candidate: CaseRubric
    old_consistency: float
    new_consistency: float
    sample_size: int
    rationale: str = ""            # "强痛点开场样本平均奖励更高" 等人话

class CalibrationReport(ContractModel):
    case_id: str
    rubric_version: int
    sample_size: int
    consistency: float
    miss_streak: int
    pending_retro_count: int       # 已发布、待指标回流的数量（"待复盘 N 条"）
    bump_recommended: bool = False
```
`CaseMemory` 保留，语义收窄为"**用户手钉的硬约束/品牌红线**"（如"必须提十年质保""禁夸功效"），生成时作硬约束注入——这是轻干预的另一条腿，与自动学习的 rubric 职责分离。

## 8. 状态机（`state_machines.py` 新增）
```python
CASE_RUBRIC_TRANSITIONS = {
    "draft": frozenset({"active"}),
    "active": frozenset({"superseded"}),
    "superseded": frozenset(),
}
RUBRIC_BUMP_TRANSITIONS = {
    "proposed": frozenset({"accepted", "rejected"}),
    "accepted": frozenset(),
    "rejected": frozenset(),
}
```
注册进 `TRANSITIONS`，状态变更一律走 `assert_transition`。`ScorePrediction` 的盲不变量（`locked_at` 后不可改、结算需晚于 lock）在 service 层守。

## 9. API 变更

### 新增（薄路由 → `services/case_rubric.py`）
- `GET  /api/cases/{id}/rubric` → `CaseRubric`（active 卡，只读）
- `GET  /api/cases/{id}/rubric/calibration` → `CalibrationReport`（智能体 tab 后视镜）
- `GET  /api/cases/{id}/rubric/bump-proposal` → `RubricBumpProposal | null`
- `POST /api/cases/{id}/rubric/bump-proposal/{pid}/accept|reject`（operator）
- 创作页生成响应里**内联**每版 `ScorePrediction`（见 §10 改 `generate_script_with_memory` 返回）。

### 下线（前期不挂 UI；保留实现，gate 在 feature flag 后）
- `POST /api/cases/{id}/reflection-runs`
- `GET  /api/cases/{id}/agent/memory-proposals`、`POST …/memory/{id}/approve|reject`
- `GET  /api/cases/{id}/insights`、`/creative-patterns`
- `POST /api/cases/{id}/agent/runs`（`goal=script_draft|memory_proposal` 的生成职责并入创作页；`brief` 导入若保留则并入数据源）

### 改造
- `generate_script_with_memory`：支持出 **N 版**（默认 3，`variation_count` 入请求），每版回 `ScorePrediction`，按 composite 排序。pairwise 奖励据此采集。
- `adopt_script_draft` / 成片导出 / `publish` / `import_metrics` / `delete_finished_video`：各加一行 `RewardSignal` 写入（事件搭车）。

## 10. 存储 / 迁移
- 新表：`case_rubrics`、`rubric_dimensions`(或 JSON 内联)、`score_predictions`、`reward_signals`、`rubric_bump_proposals`。
- Alembic：新 revision 接在 `0011` 之后（单一线性 head），放 `packages/core/storage/alembic/versions/0012_case_rubric.py`。
- 内存后端 `Repository` 同步加对应 dict。
- 冷启动：新建案例时种入一张 `cold_start=True` 的行业默认卡（均权 + starter `value_scores`）；首次有参考视频/采用脚本时 `fit` 一次 seed 权重（仍 `cold_start=True`，直到有真实 `performance_scored` 才转 false）。

## 11. Web UI

### 创作页（唯一生产入口，`apps/web/src/pages/studio/*` + `components/script-tools/ScriptGenerateModal.tsx`）
- 生成后展示 N 版，按"看好程度"排序：🔥最看好 / 👍还不错 / 一般 + 一句理由。
- 黑话翻译：硬广→"带货转化"、IP→"立人设种草"，各配一句说明；输入框 placeholder 给具体例子并标"选填"。
- 用户不感知 rubric / 盲预测 / 分数等内部词。

### 成片页（`finished_videos`）
- 删除/归档时弹一键原因（可跳过）：[脚本不行] [画面不行] [选题不行] [就是没空发] → 写 `RewardSignal.reason`。

### 智能体 tab（重定位为只读后视镜）
- 砍掉：数据源绑定、运行目标、记忆提案审批面板。
- 保留只读：本案例评分卡 vX（维度+权重）、待复盘 N 条、最近从哪些片学到了什么。
- 唯一交互：评分卡升版确认弹窗（来自 `RubricBumpProposal`）。

## 12. 分阶段交付

### P0 —— 冷启动可用，零审批（不依赖发布数据）
- 契约 `CaseRubric` / `RubricDimension` / `ScorePrediction` / `RewardSignal` + `rubric.py`（score/blind/冷启动 fit）+ 迁移 `0012`。
- `generate_script_with_memory` 出 3 版 + 每版盲预测；创作页排序展示。
- 奖励搭车：adopt / 成片 / publish / discard 四个采集点。
- 智能体 tab 只读评分卡。
- **验收**：新案例能对 3 版脚本打分排序；采用/成片/发布各落一条 `RewardSignal`；全程零审批。

### P1 —— 复盘 + 升级（有指标后）
- `import_metrics` 结算 `ScorePrediction` → 校准池；`evaluate_calibration` + `CalibrationReport`。
- `fit_weights` + 重排验证门 + `RubricBumpProposal` + 一次确认 UI。
- 废片原因采集、`stale_unpublished` 惰性奖励。
- **验收**：构造校准池后，劣化的旧卡能产出一个"新卡更准"的升版提议；盲不变量被测试守护。

### P2 —— 增强（可选）
- 跨 provider 审计升版；标杆账号库（benchmark）；评论聚类做人设；正式移除已下线的反思/提案代码。

## 13. 测试
- `tests/creative/test_case_rubric_logic.py`：score 单调性、band 边界、冷启动 fit 确定性、`evaluate_calibration` 一致性、`fit_weights` 必须更准否则不升、盲不变量（结算须晚于 lock）。
- `tests/api/test_case_rubric_loop.py`：生成→3版预测→adopt→成片→publish→import_metrics→结算→（构造劣化）→bump 提议→accept 全链路（memory + sandbox）。
- 奖励搭车点各一条断言（adopt/produce/publish/discard/metric 落 `RewardSignal`）。
- 契约/状态机：`tests/contract` 加 `case_rubric` / `rubric_bump` 迁移表；`schema.d.ts` 无漂移（改契约后 `export_openapi` + `generate:api`）。
- 回归：成片流水线 `tests/production tests/workflow` 不受影响（只在 service 层加采集，节点零改动）。

## 14. 精简 / 解耦自检（交付验收项）
- [ ] 用户面对的核心概念 = 3（评分卡 / 看好程度 / 复盘）；智能体 tab 无任何"生成"按钮。
- [ ] 脚本生成只有创作页一个入口；case_agent 不再独立生成内容。
- [ ] 常规人工仅剩"升版确认" + 可选"废片原因"；记忆无逐条审批。
- [ ] `rubric.py` 纯函数：不查 DB / 不调 provider / 不随机；有单测。
- [ ] 奖励信号只搭既有 service 动作的车，无新增用户步骤。
- [ ] 盲不变量被 service 守 + 测试覆盖（预测 immutable、结算晚于 lock）。
- [ ] 下线端点不挂 UI 但实现与数据模型保留，gate 在 flag 后。
- [ ] 契约改动已重生成 `openapi.json` + `schema.d.ts`，CI `git diff --exit-code` 绿。
- [ ] 成片流水线节点零改动（解耦验证）。
```
