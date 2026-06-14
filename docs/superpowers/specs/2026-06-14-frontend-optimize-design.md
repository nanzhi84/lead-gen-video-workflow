# 树影前端整体优化 — 设计 (2026-06-14)

## 目标与约束
- **只动前端**(`apps/web`),不改后端。实现中发现的后端缺口最后统一报告。
- **对齐 DFG0311/digital-human-Cutagent 的 origin/dev 视觉与交互**;**无感迁移**(保持结构熟悉,演进而非重写)。
- design tokens **已与旧版基本一致**(accent `#5e6d51`、amber `#d6ff48`、bg `#e9ece3`、surface `#fbfbf6`、Playfair/Noto Serif 标题、24px 圆角卡片、`.btn-*`/`.card`/`.badge`),因此本轮是**移植成熟交互模式 + 收口结构**,而非换肤。
- 隔离:worktree `worktree-frontend-optimize`;验证用该分支 dev server(新端口,代理 → 真实 API `:8000` + 真实数据)。

## 参考(旧版,只读)
旧仓库前端:`/home/nanzhi/projects/digital-human-Cutagent/frontend`(dev 分支)。
- 预览:`src/components/modals/VideoPreviewModal.tsx` + `src/components/ui/VideoPlayer.tsx`(带片段可视化)。
- 标注:`src/pages/Templates.tsx`(AnalysisResultModal / LipSyncReviewPanel / BrollStructuredReviewPanel / StructuredAnnotationEditor)+ `src/utils/annotationV4.ts`(clips↔扁平 segments 适配)+ `src/types/index.ts`。
- 案例:`src/pages/Cases.tsx` + `src/components/modals/CaseModal.tsx`(分区表单)。

## A. 案例结构收口
**决策(用户):去掉案例编辑弹窗,`CaseProfilePage` 作为唯一深编辑器。**
- `apps/web/src/pages/studio/CaseProfilePage.tsx` 升级为**完整案例编辑器**,分区:
  - 基础信息:`name` / `description` / `industry` / `product` / `target_audience`
  - 卖点画像:`key_selling_points` / `competitor_names` / `brand_keywords`
  - IP人设:`ip_persona` / `brand_voice` / `strategy_tags`
- 案例列表(`apps/web/src/pages/studio/CaseListPage.tsx`)「编辑」→ 跳转 `/studio/:caseId/profile`;「新建」→ 极简建草稿(仅 `name`)后进画像页补全。
- **移除 `CaseModal` 的编辑职能**(`apps/web/src/components/modals/CaseModal.tsx`);如新建仍需弹窗,精简为仅名称。清理 studio 「案例画像」tab 与列表编辑的重叠困惑。
- 复用现有 `parseList/joinList`、`api.cases.patch/create`。

## B. 视频模板放大预览
- 新增 `apps/web/src/components/library/VideoPreviewModal.tsx`(参考旧版 VideoPreviewModal/VideoPlayer):卡片/「预览」→ 大窗 16:9 播放器 + 元信息(标题/时长/标签/标注状态);已标注资产叠加片段标记。
- 接入 `apps/web/src/pages/library/TemplatesTab.tsx` 与 `TemplateAssetCard.tsx`:「预览」按钮打开模态(替代/补充内联播放),加载态反馈。

## C. 标注编辑器重做(结构面板 + 播放器标记)
重写 `apps/web/src/components/annotation/AnnotationEditorModal.tsx`,消灭裸 JSON:
- **适配层**:新增 `apps/web/src/utils/annotationV4.ts`(移植旧版:`clipsToSegments` / `segmentsToClips`),把 canonical(AnnotationV4: meta/clips/usage_windows/quality_events/quality_report/evidence_frames)转成扁平 `AnnotationTimelineSegment[]` + `AnnotationQualityEvent[]`。
- **左:视频播放器**(复用 B 的 VideoPlayer):时间轴叠加片段条 + 质量事件标记,点击 seek/高亮当前片段。
- **右:结构面板**:
  - 质量评估三栏(有效/无效/总时长,沿用现有指标卡)。
  - 片段卡片:start/end/duration/置信度/`usable_roles`/`keywords`/summary;口播(gaze/mouth visible/mouth moving/speech-action/intent/gesture)与 B-roll(process stage/action/narrative role/camera motion/shot scale)分字段。
  - 质量事件列表:event_type/start/end/risk_tier/confidence/description。
- 保留动作 重新分析(`api.annotations.rerun`)/裁剪无效(`trim`)/手动编辑;**手动编辑改结构化表单**(逐段增删 + 字段),保存仍走 JSON Patch(`api.annotations.patch`,带 etag 409 处理)。

## D. 整体收口(rough edges)
- 预览/重分析/上传 的加载与禁用态反馈统一(按钮文案+spinner)。
- 空/错/载入态统一走 `ui/State`(LoadingState/ErrorState/EmptyState)。
- studio 创建向导(`StudioCreatePage.tsx`)信息密度与分步收口(不改业务,仅排版/反馈)。
- 按钮/徽章/卡片样式一致性巡检,确保全站沿用 `.btn-*`/`.badge`/`.card`/`.tabLink`。

## 共享前置
- `annotationV4.ts` 适配器与 `VideoPlayer`(带片段/质量标记)为 B、C 共用 → 先建。

## 验证
- `npm run build`(tsc + vite,捕获类型错误)。
- 该分支 dev server(端口 5174,`CUTAGENT_API_PROXY_TARGET=http://127.0.0.1:8000`)+ Playwright 截图:案例画像编辑、模板放大预览、标注编辑器(结构+播放器)。

## 后端缺口报告(最后)
实现中记录"前端需要但后端没有"的能力(如标注播放器要的关键帧/缩略图、某些字段/端点),最终统一报告,本轮不改后端。
