# M6R 施工简报：Prompt 四组集中管理 + 变量 chip + 恢复默认

负责：Codex（执行）/ Claude（架构 + 验收）
分支：`feat/m6r-prompt-groups`
来源：parity 审计真缺口⑤——原版「设置-提示词」四组集中管理（脚本工作台/视频分析VL/发布封面/剪辑Agent）+ 变量点击插入 + 恢复默认；genesis 只 seed 了 3 个 prompt、prompt 页是扁平单列。

## 已勘定事实（勿推翻）

- genesis 有 Prompt Registry：`PromptTemplate(id,name,purpose,variables_schema_ref,output_schema_ref,status)` / `PromptVersion(content,status,published_at)` / `PromptBinding(template,version,node_id,case_id,priority)`；render 用 **str.format 风格**（`{var}` 是变量，正文裸花括号会 prompt.render_error——M6L 踩过）。
- 已 seed：prompt_creative_intent（→ResolveCreativeIntent）、prompt_vlm_annotation（→MediaAssetAnnotation）、prompt_case_agent_script（→CaseAgentScriptGenerate）。其余原版 prompt 未 seed。
- 已有 API：`/api/prompts`（列表/建模板/版本 CRUD/approve/publish/rollback/bindings）；前端 `apps/web/src/pages/ops/PromptManagementPage.tsx`（扁平单列 + 变量 chip 由 schema 启发式推断）。
- 原版 4 组与 key（参考只读 `/home/nanzhi/projects/digital-human-Cutagent/config/system_prompts.json` + `backend/app/config/prompt_library.py` 的默认值 + `backend/app/services/system_prompts_service.py` 的 PROMPT_FIELDS）：
  - **脚本工作台**：hard_ad 与 ip_persona 各 5（polish/fresh_generate/remix_generate/clone_generate/semantic）。变量：case_name/product_name/industry/target_audience/ip_persona/brand_voice/key_selling_points/description/strategy_tags/scene_type/duration/generation_mode（polish 另有 style/user_input；semantic 另有 title/script/publish_content）。
  - **视频分析VL**：broll_vl_analysis / broll_vl_portrait / broll_vl_scenery。变量：asset_id/asset_kind/analysis_type 等。
  - **发布封面**：ai_cover_prompt / ai_cover_reference_style。
  - **剪辑Agent**：editing_agent_prompt / _steady / _balanced / _fast。
  - 原版变量用 `{{var}}`（双花括号）或 `{var}`（单）；**迁到 genesis 一律转成单花括号 `{var}`，且正文除声明变量外不得有裸花括号**（M6L 教训）。

## 改动清单

### A. seed 原版 prompt 全量进 registry（按组）

- A1 把上述 prompt（约 19 个）seed 为 PromptTemplate + v1(published)，content 取原版默认值（`{{var}}`→`{var}`，brace-safe）。组别用 **purpose 约定**承载（不加 DB 列）：`prompt.script.hard_ad.polish` / `prompt.script.ip_persona.fresh_generate` / `prompt.vlm.broll_analysis` / `prompt.cover.ai_cover` / `prompt.editing.balanced` 等（purpose 前缀 = 组：script/vlm/cover/editing）。已 seed 的 3 个保持不动（或对齐 purpose 前缀，但**不改其 binding/内容**）。
- A2 **binding 只给有对应 genesis 节点的**（creative_intent/vlm_annotation/case_agent_script 已有，保持）；其余 prompt **不 binding**（genesis 暂无对应节点）——它们作为「可集中管理/编辑、将来可绑」的模板存在，不伪造 binding。
- A3 变量提示：给 PromptTemplate 增一个**只读的变量提示来源**——优先复用 `variables_schema_ref`；若不足，在 seed 时把每个 prompt 的变量列表写进一个可由 API 返回的字段（如 PromptTemplateView 增 `variable_hints: list[str]`，从 seed 元数据来）。供前端 chip 用。**不强制后端 schema 大改**：若加 variable_hints 字段，契约 + 视图 + sqlalchemy 行映射同步。

### B. 前端：四组 tab + 变量 chip + 恢复默认（PromptManagementPage.tsx）

- B1 顶部按 purpose 前缀分成四组 tab（脚本工作台/视频分析VL/发布封面/剪辑Agent），每组内列该组模板（沿用现有扁平列表组件，加一层 tab）。保持 M6j 扁平/稳定风格，不回退布局。
- B2 变量 chip：用 PromptTemplate 的 variable_hints（或 variables_schema 推断）渲染成可点击 chip，点击把 `{var}` 插入草稿编辑器光标处（现有 chip 插入逻辑已有，接 variable_hints）。
- B3「恢复默认」：每个模板加按钮 = rollback 到首个 published 版本（seed 的 v1）。沿用现有 rollback API。
- B4 prod 只读已发布版本不变；草稿→审批→发布流转不变。

### C. 测试

- C1 seed 单测：断言四组 prompt 都已建（按 purpose 前缀可分组）、content 用各自声明变量 `str.format` 不抛（brace-safe）、已 seed 的 3 个未被破坏。
- C2 若加 variable_hints：契约/视图/行映射单测。
- C3 `cd apps/web && npx tsc --noEmit && npm run build` 绿；schema.d.ts 同步。
- C4 全量基线（约 200）不回退；所有 pytest 包 `timeout -k 5 600`，主仓 venv。

## 边界

- 不实现原版「调试 prompt 随请求内联透传到生产节点」（spec 雷点，故意不做）——prompt 走 registry binding，不手写进请求。
- genesis 暂无对应节点的 prompt 不伪造 binding。
- 不碰 pipeline/真出片/发布。

## 验收门（验收官）

1. Playwright：prompt 页四组 tab 切换、每组列出对应模板、变量 chip 点击插入、改某 prompt 新版本→发布→恢复默认（rollback）。
2. 全量 + DB + Temporal 三套绿；tsc/build 绿。
