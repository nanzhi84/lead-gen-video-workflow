# M6T 施工简报：Broll 插入点预览 + 素材使用排行（含选材账本）

负责：Codex（执行）/ Claude（架构 + 验收）
分支：`feat/m6t-broll-preview-usage-ledger`
来源：parity 审计真缺口④。两部分：4a Broll 插入点预览时间轴（数据基本已有）；4b 素材使用排行（**genesis 无选材账本，需新建**）。

## 已勘定事实（勿推翻）

- 4a 数据基本在：`BrollPlanArtifact`（contracts/artifacts.py:271）含 `overlays:[BrollOverlay(timeline_start,timeline_end,confidence,reason)]` + `segments:[{asset_id,start_sec,end_sec,confidence}]`。**缺** matched_keywords/scene_name。`BrollPlanning` 节点（digital_human.py:1616）目前 confidence=1.0、start=index*3（简化）。RunDetailModal（apps/web/src/components/runs/RunDetailModal.tsx）显示 artifacts 但无时间轴可视化。
- 4b **没有选材账本**：genesis 不记 per-run「最终选了哪个素材」。最终选择**在 plan 产物里**（portrait_plan/broll_plan/style_plan 的 asset_id/overlays/segments）。`MaterialPackPlanning` 出候选、无下游落选材记录。原版有 `case_selections`（case_id,task_id,medium,item_id,diversity_key,ts）账本 + usage-ranking 服务。

## 改动清单

### A. 选材账本（4b 的数据底座）

- A1 新增 `selection_ledger` 表（id, case_id, run_id, medium[portrait|broll|bgm|font], asset_id, slot_phase, diversity_key, created_at）+ alembic 迁移 + bootstrap schema。sqlalchemy repo 加写入 + 查询。
- A2 在 `_finalize_run_report`（仅成功路径，digital_human.py ~2237）**事后读本 run 的 plan 产物**（portrait_plan/broll_plan/style_plan/bgm 选择）提取被实际选用的 asset_id，按 medium 落 selection_ledger（幂等：同 run 重复 finalize 不重复写）。best-effort try/except 不阻断（沿用 M6O 清理那段的风格）。
- A3 排行查询服务 + 端点 `GET /api/library/assets/{kind}/usage-ranking?case_id=&top_n=`：从 selection_ledger 聚合 task_use_count（distinct run）、segment_use_count、last_used_at、recent_score（近 N run 加权）；用资产元数据装饰。新契约 `MaterialUsageRankingReport`。

### B. Broll 插入点数据补全（4a，可选增强）

- B1 `BrollOverlay` 增 `matched_keywords:list[str]=[]`、`scene_name:str|None`（契约 + artifact schema 版本兼容，默认空，不破坏旧产物）；`BrollPlanning` 节点在有信息时填（无则留空，**不强行编**）。
- B2 不改 broll 选材语义（确定性，不引入随机/LLM 关键词强依赖）；keywords 来自素材标注（若标注有），无则空。

### C. 前端（apps/web）

- C1 RunDetailModal 加 `BrollTimelinePreview` 组件：解析 plan_broll 产物 → 水平时间轴（按 timeline_start/end 定位色块）+ confidence 三档色（>0.7 绿 / 0.4-0.7 黄 / <0.4 橙）+ 悬浮显序号/title + 详情列表（keyword chips + 缩略图占位）；overlays 为空显「0 命中」排查 toast/文案。沿用 M6j 扁平风格。
- C2 素材库卡片（library/TemplateAssetCard 等）加「使用」徽标（task_use_count + last_used_at）；案例工作台或素材库加「使用排行」面板（调 usage-ranking 端点，按 medium 排序，使用次数筛选）。
- C3 api client + schema.d.ts 同步。

## 测试

- D1 selection_ledger 写入单测（finalize 后按 plan 落账、幂等）；usage-ranking 聚合单测（task_use_count/recent_score）。
- D2 BrollOverlay 新字段兼容单测（旧产物默认空）。
- D3 `cd apps/web && npx tsc --noEmit && npm run build` 绿；schema.d.ts 同步。
- D4 全量基线（约 200）不回退。所有 pytest 包 `timeout -k 5 600`，主仓 venv。DB 集成验收官在外面跑。

## 边界

- 不做原版 diversity_cluster/opening_guard 等复杂多样性算法（只做 use_count/recent/last_used 基础排行；多样性选材本就由 pipeline 确定性逻辑管）。
- 不引入随机/LLM 强依赖到 broll 选材。
- 4a keyword/scene 无来源时留空，不编造。

## 验收门（验收官，真 run live）

1. 跑几条真 run 后，selection_ledger 有记录；素材库卡片显使用次数、使用排行端点返真排序。
2. RunDetail 的 Broll 时间轴：有 broll 的 run 显插入点色块+confidence 色；无 broll 显「0 命中」。
3. 全量 + DB + Temporal + tsc/build 绿。
