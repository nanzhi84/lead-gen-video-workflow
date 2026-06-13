# M6S + M6T 验收记录（Wave 2，真 live）

负责：Codex（执行）/ Claude（架构 + 验收）
合并：`6841691` Merge M6S、`b5eb971` Merge M6T、`8b49d54` 重新生成 openapi/schema.d.ts（均入 main）
验收日期：2026-06-13

补做 parity 审计 5 个真缺口的第二波：②对标视频参考提取 Part A（M6S）；④Broll 插入点预览 + 素材使用排行/选材账本（M6T）。

## 离线验证（合并后 main，组合验证）

- 后端全量：`.venv/bin/python -m pytest` → **全绿，0 失败**（M6S+M6T 与既有 M6Q/M6R 合并后一起跑；M6S 单独 224 passed/9 skipped，M6T 单独 204 passed/23 skipped）。
- 前端：`npx tsc --noEmit` exit 0；`npm run build` ✓ built。
- 合并后 `openapi.json` 经 `export_openapi.py` 重新导出**零 diff**（Codex 手工编辑 + git 自动合并均正确）；`schema.d.ts` 经 `npm run generate:api` 重新生成为权威版（仅排序差异）。两份合并文件已用生成器校正。

## Live 验证（demo 环境，alembic 升到 0003_selection_ledger，重启于合并代码，装 yt-dlp）

### M6S 对标提取（门 #1）

- 端点 `POST /api/creative/reference-extract`：非法 URL → `reference.unsupported_platform` 400（接线 + 错误码映射真）。
- **真实抽取**（独立脚本跑真 `extract_reference`，proxy 直连 YouTube）：
  - URL `youtube.com/watch?v=aircAruvnKk` →
  - **source=subtitle**（字幕优先、未触发 ASR，正确）、platform=youtube、title「But what is a neural network? | Deep learning chapter 1」、duration=1120s、**真转写 18458 字**。
  - yt-dlp 懒加载（模块无 yt-dlp 也能 import，全量不崩）已验证。
  - 已知小瑕疵（非 blocker）：WebVTT 头「Kind: captions Language: en」会带进转写开头，留作 M6S-polish 跟进（strip VTT 头）。

### M6T Broll 预览 + 选材账本（门 #1/#2）

- migration `0003_selection_ledger`（down_revision=0002）应用，`selection_ledger` 表建。
- **真数据落账**：用 4 条真实成功 run 的 plan 产物（plan.portrait/broll/style），按 `_selection_entries_from_state` 同款逻辑落账 → **12 行**（portrait/bgm/font × 4，broll=0 因这些 run 无 broll）；重复跑插入 0（**幂等真**）。
- **usage-ranking 端点真聚合**：portrait/bgm/font 各 task_use_count=4（4 个 distinct run）、segment_use_count=4、recent_score=2.083、真 last_used；broll 空（无假数）。
- 前端（Playwright）：
  - 素材库 BGM tab：**使用排行**面板「#1 Demo background music · 4 次 · asset_bgm_demo · 片段 4 · 最近 刚刚」；卡片**使用 4** 徽标。
  - RunDetail：**B-roll 插入点** 时间轴组件渲染，无 broll 的 run 显 **0 命中** 空态（brief 门 #2 的空态分支）。
  - 注：暂无含 broll overlay 的真 run，故色块/confidence 三档色未 live 跑到（组件逻辑已评审 CLEAN，空态已验）。

截图：`m6t-bgm-usage-ranking.png`、`m6t-run-broll-timeline.png`。

## 审查

两个 Explore 评审 agent 对 M6S/M6T staged diff 逐条核验 → 均 CLEAN：M6S 严守 Part A（无 RPA/Playwright）、yt-dlp 懒加载、错误码定义齐、无 case 资产副作用；M6T migration down_revision/表结构一致、finalize 幂等+best-effort 隔离、broll 选材语义未动、BrollOverlay 新字段向后兼容。

## 结论

5 个真缺口（M6Q/M6R/M6S/M6T 共 4 个里程碑覆盖①③⑤②④）全部补做完成，离线三套绿 + live 真数验证通过。下一步 M6V：把 Mac mini dev 侧真实资产（3 case/12 BGM/broll/fonts）迁到 OSS + 建索引（简报 `M6V-asset-migration.md` 已就绪）。

## 待跟进

- **M6S-polish**：strip 转写开头的 WebVTT 头（`Kind: captions`/`Language:`），小改、不阻断。
