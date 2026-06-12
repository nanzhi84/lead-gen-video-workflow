# M6j 施工简报：前端布局稳定 + 扁平化（去卡片嵌套）

负责：Codex（执行）/ Claude（设计规范 + 验收）
分支：`feat/m6j-ui-flatten`
背景：产品负责人 UI 反馈（带截图，docs 不附）三个同源问题——① 提示词页难用：不知道每个 prompt 用在哪、
版本 diff 区文字框乱浮动；② 创作 5 步向导切上一步/下一步整页大幅浮动；③ 全站卡片套卡片（card-in-card），AI 味重。
根因（Explore 诊断，file:line 见下）：**用嵌套盒子表达层级** + **容器无固定高度致 layout shift**。

## 核心设计理念（架构师定，不要偏离）
**用排版表达层级，而非用嵌套盒子表达层级。** 保留纸感色板/品牌绿/字体（用户认可的，不动 token 颜色），
但把"盒子套盒子"换成"标题层级 + 留白 + 对齐 + 极轻分隔线"。视觉参考克制的专业工具 dashboard
（Linear/Stripe 后台那种信息密度与克制），不是营销落地页的玻璃大卡片。

### 三条硬规则

**规则 1 — 布局稳定（消除 layout shift）**
- 任何因交互（切步/切版本/选择）改变内容的区域，**容器尺寸必须恒定**：固定 `min-h` + 必要时 `max-h` + 内部 `overflow-auto`。
- 创作 5 步向导：步骤内容区固定高度（`min-h-[520px]` 量各步最高态取值），「上一步/下一步」操作栏固定在卡片底部
  （flex 布局 content 区 flex-1 + footer 固定），切步时**按钮位置和卡片总高不变**；步骤指示条本身不跳动。
- 提示词版本 diff：diff 区 `min-h-[360px] max-h-[360px] overflow-auto`，选不同版本时上方下拉、下方按钮**不位移**。

**规则 2 — 去卡片嵌套（扁平化）**
- `.card` 只作**页面级一层**容器。**禁止 `.card` 内再套 `.card` 或伪卡片**。
- **删除全站伪卡片**：`rounded-[20px]/rounded-2xl + border + bg-white/60~65 + p-3~4` 这种到处手写的内层盒子全部去掉。
- 卡片内子分区改用：**小标题**（`text-sm font-medium text-text-secondary`）**+ 留白**分隔；需要更强分组时用**顶部 1px 分隔线**（`border-t border-border/60 pt-4 mt-4`），**不要四面边框盒子**。
- 列表项（run/draft/binding/数据源/记忆提案/case 计数等）：用**行式**——`divide-y divide-border/60` 的行 + hover 底色（`hover:bg-hover`），**不是每条一个圆角边框卡片**。
- 案例中心 case 卡片内的"脚本数/素材数/标签数"三个小盒子 → 改**内联文本**（`X 脚本 · Y 素材 · Z 标签`）。
- 降低视觉重量：减少圆角层级、阴影只在最外层 .card 出现一次。

**规则 3 — 功能可见（提示词用途）**
- 提示词页顶部加一句话：每个提示词模板对应系统哪个环节（节点）。
- 模板列表每项显示**绑定摘要**：用 PromptBinding 的 node_id/case_id（schema.d.ts PromptBindingView 有），
  显示"用于 {node_id}"或"未绑定"，让用户一眼知道这个 prompt 用在哪个 pipeline 节点。
- 当前 prompt 详情区也显示其全部绑定（节点/Case/优先级/启用），与模板选择联动。

## 页面级改动（按反馈优先级）

1. **提示词页** `apps/web/src/pages/ops/PromptManagementPage.tsx`（+ 子组件）
   - 去 3 层卡片嵌套（L1 card + L2 grid + L3 变量盒子）→ 单层 card 内用分区标题+分隔线。
   - diff 区固定高度（规则1）。模板列表项显示绑定摘要（规则3）。顶部加用途说明。

2. **创作 5 步向导** `apps/web/src/pages/studio/StudioCreatePage.tsx` + `components/studio-create/*`
   - 步骤内容区固定 min-h + footer 固定（规则1）。配置摘要侧栏稳定不跳。

3. **案例智能体页** `apps/web/src/pages/studio/CaseAgentPage.tsx` + `components/case-agent/*`
   - AgentRunsPanel/AgentDraftsPanel/SourceBindingPanel 的伪卡片（rounded-[20px] border bg-white）→ 行式列表 + 分隔线（规则2）。

4. **案例中心** `apps/web/src/pages/studio/CaseListPage.tsx`
   - case 卡片内三计数小盒子 → 内联文本（规则2）。

5. **全站清扫**：grep 其余 `rounded-[20px]/rounded-2xl + border + bg-white/6` 伪卡片模式，按规则2 扁平化（素材库/发布/统计页若有同款也一并；但本批聚焦上述 4 页 + 明显的全站伪卡片，过大的页面可标记留后续）。

## 边界
- 不动色板/品牌色/字体 token（用户认可）；不动后端；不改业务逻辑/路由/功能，只改布局与视觉层级；
- 与 M6i（后端真 provider 接通）并行，尽量不碰 voices 业务逻辑（M6i 地盘），只做纯 UI 布局。

## Verification（sandbox 内）
- `cd apps/web && npx tsc --noEmit && npm run build` 绿；不引新依赖；文件 ≤400 行。
- 自查：grep `.card`，确认无 .card 套 .card；grep 伪卡片模式确认目标页已清除。

## 验收门（验收官 Playwright 截图对比）
1. 提示词页：切版本 diff 不浮动；模板项显示绑定用途；无卡片套卡片。
2. 创作向导：切上一步/下一步，卡片总高与按钮位置不变（layout 稳定）。
3. 案例智能体/案例中心：无伪卡片嵌套，改行式/内联。
4. 整体观感：扁平、稳定、专业工具感，无明显 AI 味卡片堆叠。
