# packages/creative

Case 领域的创意/脚本生成与「自进化」存储层，外加 URL 参考视频抽取。提供 Case CRUD、Case Agent 运行/草稿/记忆提案的 DB 落库，以及从参考链接抽取脚本（字幕优先，无字幕走 ASR）。被 `apps/api/services/case_agent.py`、`apps/api/routers/creative.py`、`apps/api/routers/case_agent.py` 调用。

## 职责
- Case CRUD 与列表派生计数（material/script/voice/quality）：`cases/sqlalchemy_repository.py`，计数按 R6 规则在 `_counts_for_cases` 内现算（schema FK 不齐）。
- Case Agent 学习闭环的 DB 落库：source binding、agent run、脚本草稿/版本、记忆提案与审批、reflection、knowledge/insights/creative_patterns、记忆制导脚本生成（`cases/sqlalchemy_learning.py`）。
- Row→contract 映射全部集中在 `cases/sqlalchemy_learning_mappers.py`。
- URL 参考视频抽取（`reference_extract.py`）与运营手贴 cookie 管理（`reference_cookies.py`）。

## 关键文件
- `cases/sqlalchemy_learning.py` — `SqlAlchemyCaseLearningRepository` + `BriefFields`；记忆状态流转走 `assert_transition("case_memory", ...)`（proposed→approved→active）。当前 agent 产物多为占位文案（`start_agent_run`、`generate_script_with_memory` 写死示例脚本/insight），尚无真实生成算法。
- `cases/sqlalchemy_repository.py` — `SqlAlchemyCaseRepository`，Case CRUD 与派生计数。
- `reference_extract.py` — `extract_reference` / `fetch_metadata`（yt-dlp 取信息+字幕，`source` 为 `subtitle`/`asr`；ASR 与 ObjectStore 经参数注入；含抖音 `_DouyinExtract` 兜底）。
- `reference_cookies.py` — header/netscape/json 三格式 cookie 解析、SecretStore 持久化、`cookie_status`/`test_cookies`/`refresh_status`。

## 约定与要求
- contract-first：I/O 走 `packages.core.contracts`；本包是存储/抽取层，纯算法（评分、特征、召回、置信度门控）目前并不存在于此。
- 记忆状态流转必须经 `assert_transition("case_memory", ...)`；记忆必须人工 approve/reject。
- cookie auto-refresh（Playwright）刻意不实现：`refresh_status()` 恒返回 `auto_refresh_supported=False`，对应 `/api/creative/reference-extractor/refresh-cookies` 端点返回 410；运营手动粘贴 cookie。
- 投放指标导入（matching_policy / strict_manual / publish_record 匹配）不在本包——实现在 `packages/production/sqlalchemy_repository.py` 的 `import_metrics`，本包无 `metrics_import.py`。

## 测试
- `pytest tests/creative`（仅 `test_reference_extract.py` / `test_reference_cookies.py`）。yt-dlp/ASR/ObjectStore 均经参数注入或 monkeypatch，单测不触网；learning/repository 层无独立单测，靠 API 层覆盖。

## 注意 / 坑
- `packages/creative/__init__.py` 仅一行 docstring；无 `evolution.py`、无 `script/` 子目录。
- 改 `packages/core/contracts` 后需按根 CLAUDE.md 重新生成 openapi.json + schema.d.ts。
