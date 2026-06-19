# 发布方案迁移：自研 Playwright → CDP 驱动小V猫

> 设计文档 · 2026-06-19 · 状态：**待用户评审**（评审通过前不动任何代码）

## 0. 一句话

删掉至今未启用、平台 UI 需自维护的**自研 Playwright 多平台发布**，改回**经 CDP 驱动小V猫桌面端**发布；**小V猫成为平台账号 / 登录 / 会话的唯一事实源**，但**二维码登录与重新登录的运营入口仍保留在自家 Web dashboard**（底层从"驱动平台站点"改为"驱动小V猫"）。

---

## 1. 背景与已定决策

### 1.1 为什么掉头
- 2026-06-18 的 8-PR 路线图（#24–#28，PR1–4 已并入 main）方向是**自建发布中心替换小V猫**，自研用 Playwright 直连抖音/快手/视频号/小红书创作者后台。
- 该自研方案**至今未启动**，且 4 个平台的**上传成功检测全是 UNVERIFIED**；更根本的问题是：**N 个敌对平台后台**各有登录、上传流程、反爬风控，且服务端随时变、你不可控——长期维护成本高。
- 小V猫是成熟的免费桌面端（杭州宝特云，v2.0.0），矩阵发布覆盖抖音/快手/视频号/小红书/头条/B站，平台 UI 变动由小V猫团队承担。

### 1.2 调研硬结论（决定方案形态）
- **小V猫无任何官方 API/SDK/CLI**；唯一对外"接口"是出站 Webhook（只推通知到企微/飞书/钉钉），**收不了发布指令**。
- 因此"接入小V猫"在本系统里只能是**CDP 驱动其 Electron/Chromium 桌面端**——这正是上一代系统 `digital-human-Cutagent` 跑过的路（被 PR1 删掉的 `connectors/xiaovmao_cdp.py` 是其忠实移植，git 可恢复）。
- 维护面因此从「N 个平台后台」收敛到「小V猫一个可锁版本的内部表单」；**不是零维护**（仍用非官方 CDP 绑死小V猫内部 UI/`CatBridge`，小V猫升版可能要修选择器），但只剩一个面、且版本可控（可禁用小V猫自动更新、钉死验证过的版本）。

### 1.3 三项已敲定决策
1. **集成模型 = CDP 驱动小V猫**（恢复旧方案做底子）。
2. **小V猫 = 账号/登录/会话唯一事实源**：账号经 `CatBridge.getAllAccounts` 实时读；平台登录态存小V猫，**不再进自家 SecretStore/DB**。删除自研 SecretStore 平台会话存储。
3. **QR 登录 UX 保留在自家 dashboard**：后端改为经 CDP 驱动小V猫"加号/重登"、抓小V猫的二维码推回 dashboard，轮询小V猫 `isLogin`。`clients`/`case_publish_targets` 绑定保留；发布运维 dashboard 保留改造。

---

## 2. 现状家底（当前 HEAD 实测）

- **迁移 head = `0016_finished_video_number`**（线性单链，位于 `packages/core/storage/alembic/versions/`）。
- **`publish_accounts` 即账号表**（无独立 accounts 表），含 4 个自研会话列：`session_secret_ref`、`session_status`、`session_expires_at`、`last_validated_at`（`packages/core/storage/database.py` PublishAccountRow，约 L852）。
- `clients`、`case_publish_targets` 表存在且保留。
- **worker 无任何发布 workflow/activity**——发布走 API 同步路径（`apps/api/services/publishing.py`）。
- `XIAOVMAO_ADAPTER_ID/XIAOVMAO_PLATFORM_KEY_MAP/XIAOVMAO_PLATFORM_NAME_MAP` 三常量已被 PR1（commit f4baeee）删除，全仓零命中。
- 自研发布 footprint（约 1217 行）：`packages/publishing/platform_adapter.py` 的 `BrowserPublishAdapter` + 整个 `packages/publishing/browser/`（`playwright_driver.py` 345 / `platforms.py` 127 / `driver.py` 117 / `login_registry.py` 87 / `__init__.py` 30）+ `publish_executor.py` 95。
- 后端 QR 登录三件套 + 校验：`apps/api/services/publish_login.py`（经 Playwright `publish_browser_driver` begin/poll/validate，`store_account_session` 落 SecretStore）。
- 契约：`packages/core/contracts/publish_accounts.py`、`publishing.py`。
- 前端发布面：`PublishCenterPage`、`PublishOpsPage`、`QrLoginDialog`、`components/publish/*`、`api.publishOps`（13 方法）。`publishModel.ts` 有 5 平台（含 B 站），schema/Ops/QrLogin 仅 4 平台。
- 依赖：`pyproject.toml` 现有 `playwright`；CDP 需 `websockets`。

---

## 3. 目标架构

### 3.1 运行拓扑（已确认：与小V猫同机 Mac Mini）
- 小V猫运行在 **Mac Mini 真机**，启动时带 `--remote-debugging-port=9222`（Electron 透传 Chromium flag）。
- **承载 CDP 连接的进程与小V猫同机**（默认即 API/发布服务跑在 Mac Mini 上，沿用现有 `app.py` lifespan 在单机装配 driver 的形态）。CDP host/port 经 env 可配：`CUTAGENT_XIAOVMAO_CDP_HOST`（默认 `127.0.0.1`）、`CUTAGENT_XIAOVMAO_CDP_PORT`（默认 `9222`）。
- **成片文件须落到小V猫所在机器的本地路径**后再经 `DOM.setFileInputFiles` 喂入（小V猫从本地磁盘读视频）。`resolve_video`（从对象存储下载成片到本地临时文件）保留改造。
- 若希望 API 跑在别处（非 Mac Mini）：remote-debugging-port 默认只绑 loopback，需 SSH 隧道或在 Mac 上放一个薄 CDP-agent 暴露给 API——**列为备选，默认不走**。

### 3.2 发布通路（resurrect + 扩展）
1. 恢复 `packages/publishing/connectors/xiaovmao_cdp.py`（357 行，已存于 job tmp），补回 3 个 `XIAOVMAO_*` 常量到 `platform_adapter.py`。
2. 以 `XiaoVmaoPublishAdapter`（`adapter_id="xiaovmao.cdp"`）形态接回 `_PUBLISH_ADAPTERS` 注册表，复用现有 `PublishPlatformAdapter` 端口 + `PublishPayload`/`PublishOutcome` + `select_adapter`。
3. 发布：worker/服务经 CDP 连小V猫 → `set_files_by_index('input[type=file]', 0, [本地视频])` 注入成片 → `_fill_text_js`/`_fill_tags_js` 填标题/文案/标签（封面经 cover_node 生成后注入）→ 由小V猫发各平台。
4. 多账号 fan-out 复用 `publish_executor.run_item_publish`（去掉 `resolve_session→storage_state` 这条 SecretStore 依赖，缺会话改判小V猫 `isLogin`）；账号匹配复用 `account_matching.match_account`（纯函数，恢复的 CDP 文件已直接 import）。

### 3.3 账号 = 小V猫为源（本地表降级为绑定锚点）
- 列账号：经 CDP `CatBridge.getCall('AccountManager.getAllAccounts')` 实时读（含 `isLogin`/platform/nickname/uid）。
- 本地 `publish_accounts` 行降级为**绑定锚点**：承载 `client_id`（客户分组，小V猫不管）+ `platform` + **`xiaovmao_uid`（新增列，映射到小V猫账号）** + nickname。
- 对账语义：list 时把"小V猫真实账号集（权威，含 isLogin）"与"本地锚点行（含 client 绑定）"join；小V猫里有、本地没绑 client 的账号显示为"未绑定"。
- "会话健康"由**实时 `isLogin` 计算**（不存库），在 list 响应里回给 dashboard（视频号 24h 掉线 → isLogin=false → dashboard 提示重登）。

### 3.4 登录通路（必达目标 + 最大风险点，见 §4）

> **优先级（用户决策 6）**：登录可驱动性是**必达目标，不是锦上添花**。未来多客户多账号若靠运营去小V猫 GUI 逐个扫码无法规模化，所以必须全力打通"在自家 dashboard 内经 CDP 驱动小V猫登录"。
- dashboard QR 弹窗不变；后端 `begin_login` → CDP 触发小V猫"加号/重登" → 定位小V猫渲染二维码的 CDP target → 抓二维码 data-url/截图推回 → `poll_login` 轮询该账号 `isLogin` → 成功即 dashboard 标记已登录。会话归小V猫，**不再 `store_account_session`**。
- `PublishLoginRegistry`（app.state 上的 pending-login 内存注册表）结构与驱动无关，**保留改造**（完成判定从 `driver.poll_login(storage_state)` 改为轮询小V猫 isLogin）。

---

## 4. 关键风险与 Phase 0 PoC（必须最先打通）

**风险**：恢复的旧 CDP 文件只用了 `CatBridge.getAllAccounts`（**只读账号**），**从未驱动登录**。"经 CDP 触发小V猫加号/重登 + 抓它的二维码 + 轮询登录态"是**全新地盘**，且小V猫是非官方被驱动对象。

**Phase 0 PoC（对着真小V猫 v2.0.0 验证，零真账号即可大部分验证）**，明确三件事：
1. **能否程序触发登录**：`CatBridge` 是否暴露 `AccountManager.addAccount/login` 之类方法？若无，能否经 DOM 点"添加账号"按钮触发？
2. **能否抓到二维码**：小V猫加号时二维码在哪个 CDP target / iframe / `<img>`？能否 `Page.captureScreenshot` 或读 data-url 推回 dashboard？（可复用旧记忆里"跨 frame 找正方形 data-url img/canvas"的经验。）
3. **能否判定登录成功**：轮询 `getAllAccounts` 的 `isLogin` 是否在扫码后翻 true？

**降级兜底（仅临时安全网，非终态）**：万一 PoC 证明"在 dashboard 内驱动小V猫登录"暂不可行，则**临时**降级为——运营在小V猫 GUI 内完成首登/重登，dashboard 只读展示账号健康（isLogin）+ 提示哪个号该重登，保证主线（删自研 + CDP 发布 + 账号读取）不被阻塞。但据决策 6，**这只是过渡**：要持续投入打通 CDP 驱动登录（如换 CatBridge 方法探测、DOM 点击触发、跨 frame 抓码等多路尝试），不接受"长期靠 GUI 登录"作为终态。

---

## 5. 删除清单（DELETE，整文件/整函数删）

| 路径 | 为什么删 |
|---|---|
| `packages/publishing/browser/playwright_driver.py`（345） | 自研 Playwright QR 登录/会话校验，CDP 方案下登录归小V猫，无可复用 |
| `packages/publishing/browser/platforms.py`（127） | 4 平台直连后台的登录 URL/选择器，CDP 后由小V猫负责，不再需要 |
| `packages/publishing/account_sessions.py`（62） | `store_account_session`/`clear_account_session`——SecretStore 平台会话存储，会话归小V猫 |
| `apps/api/services/publish_accounts.py :: set_account_session` | storage_state→SecretStore 入口，无 CDP 对应物 |
| `tests/publishing/test_playwright_driver_platforms.py` | 测的是被删目标 |
| `platform_adapter.py :: BrowserPublishAdapter`（约 L130-387，含 `_publish_douyin/_shipinhao/_kuaishou/_xiaohongshu`）+ 从 `_PUBLISH_ADAPTERS` 去掉 `'browser.playwright'` 键 | 自研 Playwright 上传，UNVERIFIED 永远失败 |

---

## 6. 改造清单（GUT 删大半 / ADAPT 改造复用）

**packages/publishing**
- `platform_adapter.py` **GUT**：保留端口 + PublishPayload/PublishOutcome + Sandbox + 注册表/选择器；删 BrowserPublishAdapter；**补回 3 个 `XIAOVMAO_*` 常量**；注册 `xiaovmao.cdp` adapter。
- `browser/driver.py` **GUT**：保留 `BrowserSessionDriver` 端口 + LoginHandle/LoginPollResult/SessionCheck + `select_browser_driver` 选择器骨架 + SandboxBrowserDriver（测试默认）；删 Playwright 懒导入分支（L113-116）；新增小V猫 CDP driver；去掉 `LoginPollResult.storage_state_json`。
- `browser/__init__.py` **GUT**：同步 `__all__`（保住 `apps/api` 依赖的 `BrowserSessionDriver/PublishLoginRegistry/select_browser_driver` 签名）。
- `browser/login_registry.py` **ADAPT**：pending-login 注册表结构复用，完成判定改轮询小V猫 isLogin。
- `publish_executor.py` **ADAPT**：fan-out 编排复用；去掉 `resolve_session(account_id)→storage_state`（L31-43），缺会话改判 isLogin；`resolve_video` 保留。
- `accounts_repository.py` **GUT**：clients/case_publish_targets/accounts CRUD 保留；删 `set_account_session/get_account_session_ref` 这套 secret_ref 编排；`archive_account` 解耦 session_status；**新增 `xiaovmao_uid` 锚点列读写**。
- `accounts_mappers.py` **GUT**：client/target 映射保留；publish_account 映射的 session 字段改映射小V猫态（或保留字段语义改为 isLogin）。
- `__init__.py` **GUT**：导出清单加 CDP adapter 入口（`probe_xiaovmao_accounts/publish_via_xiaovmao` 或 `XiaoVmaoPublishAdapter`）。
- **恢复** `connectors/xiaovmao_cdp.py`（从 `git show f4baeee^:...` 或 job tmp 副本），按新端口/login 扩展。

**apps/api**
- `services/publish_login.py` **GUT（改动最大）**：begin/poll/cancel/validate 函数签名（router 入口）保留；底层全改 CDP 驱动小V猫；删所有 `publish_browser_driver`/`store_account_session`/`secret_store` 调用。
- `services/publishing.py` **GUT/ADAPT**：`_build_publish_runner` 的 `resolve_session`(SecretStore) + `select_adapter`(Playwright) → CDP 注入小V猫；`_active_publish_targets` 删 `session_status=='active'` 门禁，改 isLogin；`submit_publish_batch`/funnel/dry_run/scheduled/copy 逻辑保留；`platform_accounts` 改读小V猫 getAllAccounts。
- `services/publish_accounts.py` **ADAPT/GUT**：clients & case-target CRUD KEEP；账号 list 改读 CatBridge；`_clear_account_publish_state` 删 SecretStore.disable + cancel_logins，仅留 `delete_targets_for_account`；清理 `store_account_session/secret_store` import。
- `app.py`（L69/L127-130）+ `common.py`（L111-115） **GUT/ADAPT**：lifespan 装配从 Playwright driver 改为 CDP 客户端（`127.0.0.1:9222`，env 可配）；`PublishLoginRegistry` 保留改造。

**前端 apps/web**
- `QrLoginDialog.tsx` **KEEP**（UX 不变，二维码来源改抓小V猫）。
- `PublishOpsPage.tsx` **ADAPT**：删自研会话健康，账号改小V猫拉、health 用 isLogin；加"小V猫连接状态"。
- `PublishCenterPage/PublishReviewStep` **ADAPT**：沙盒文案改"经小V猫发布"。
- `api/client.ts`：`publishOps` **GUT**（validateSession/账号写库退化，扫码改驱动小V猫）；`publishing` **ADAPT**（删死方法 `platformAccounts`，余随契约重生成）。
- 顺手统一 `publishModel.ts` 与 schema 的平台集（4 vs 5/B站）。

---

## 7. 保留清单（KEEP，原样不动）

- `account_matching.py`（纯函数：账号组路由/标签归一化/北京时区定时）
- `copy_node.py` / `cover_node.py`（文案/封面生成——产出正是注入小V猫表单的内容）
- `sqlalchemy_repository.py` / `sqlalchemy_mappers.py`（发布物 package/batch/item/attempt 落库 + §9.5 漏斗——dashboard 数据底座）
- `services/publishing.py` 的发布包/批次/条目/attempt CRUD + copy/cover/preview 节点端点
- clients CRUD、case→target 绑定（router + service + 契约 Client/CasePublishTarget）
- `core/storage/secret_store.py`（仅切掉发布会话用途，secret_store 仍被 secrets 域等用）
- worker（无发布 workflow，不动）

---

## 8. 连带：契约 / 迁移 / 依赖 / 测试

- **迁移**：新增 `0017_drop_publish_account_session_cols`（down_revision=0016）——drop `session_secret_ref`/`session_expires_at`/`last_validated_at`；`session_status` 二选一：**(a) 一并 drop**（账号健康改由 list 时实时 isLogin 计算，不存库，最干净）或 **(b) 保留并改语义**映射 isLogin。新增 `xiaovmao_uid`（nullable）。同步 `database.py` PublishAccountRow ORM。
- **契约重生成（CI `git diff --exit-code` 守卫）**：`PublishAccount` 去/改 session 字段、QR/validate 响应若动字段 → 必须 `python scripts/export_openapi.py && (cd apps/web && npm run generate:api)` 重生成 `openapi.json` + `schema.d.ts`。Client/CasePublishTarget 不动则不触发。
- **依赖** `pyproject.toml`：删 `playwright`，加 `websockets>=12`（CDP 用，旧文件懒 import）。
- **测试**：DELETE `test_playwright_driver_platforms.py`；GUT `test_platform_adapter.py`（删 browser 用例）、`test_browser_driver.py`、`test_publish_login.py`、`test_publish_executor.py`、`test_accounts_repository.py`（删 session 断言）；新增 `test_xiaovmao_cdp.py`（mock CDP/websockets 测注入与 isLogin 判定）；KEEP `test_publishing_funnel.py`、`test_case_publishing_ops.py`（sandbox 路径）。`conftest` 默认 `CUTAGENT_ALLOW_SANDBOX_FALLBACK=1` 仍走 sandbox。

---

## 9. 分期 PR 路线

- **PR0 — PoC（spike，不并主线或以 feature flag 隔离）**：对真小V猫验证 §4 三问；产出"login 可驱动性"结论 + 二维码抓取/isLogin 轮询样例。决定 §3.4 走"dashboard 内登录"还是"降级只读健康"。
- **PR1 — 删自研 Playwright footprint**：DELETE 清单 + 从注册表摘 `browser.playwright` + 删 playwright 依赖 + 修红测试到绿。**纯减法，独立可合**（此时发布暂回 sandbox/显式不可用，不伪造）。
- **PR2 — 恢复并接回 CDP 发布 adapter**：补 `XIAOVMAO_*` 常量、恢复 `xiaovmao_cdp.py`、注册 `xiaovmao.cdp`、改 `publish_executor`/`_build_publish_runner` 走 CDP、`resolve_video` 落地、env 配 CDP host/port。账号 list 改读 CatBridge。
- **PR3 — 会话/账号事实源切换**：迁移 0017 + 契约重生成 + `accounts_repository`/mappers GUT + 删 `account_sessions.py`/`set_account_session`。
- **PR4 — 登录通路**：按 PR0 结论实现"dashboard 驱动小V猫登录抓码"或"只读健康 + GUI 登录"；`publish_login.py` GUT 改造 + `PublishOpsPage`/`QrLoginDialog` 接线。
- **PR5 — 前端收口 + 真机联调**：平台集统一、文案改写、Mac Mini 真账号端到端发布验收。

每个 PR 独立通过 `scripts/ci_gate.sh`（含契约漂移守卫）。

---

## 10. 验收门禁
- 发布域 + 漏斗 + golden + contract 零回归；ruff 干净（line-length 100）；前端 `npm run build` exit 0；无 openapi/schema 漂移。
- 真机：小V猫带 9222 起、账号已登录 → 系统提交 case → 小V猫表单被正确填充并发出（PR5 用真账号验，UNVERIFIED 处显式失败、不伪造）。

---

## 11. 已定决策（2026-06-19 用户确认）

1. **运行拓扑**：承载 CDP 的进程与小V猫**同机 Mac Mini**，API 不跑别处（CDP 走 loopback `127.0.0.1:9222`）。
2. **`session_status` 列**：**直接 drop**；账号健康一律由 list 时**实时算小V猫 `isLogin`、不存库**（§8 走 (a)）。迁移 0017 drop `session_secret_ref/session_status/session_expires_at/last_validated_at` 四列、加 `xiaovmao_uid`。
3. **PoC 顺序**：**PR0 spike 先行 → PR1/PR2 并行推进**（登录降级兜底保证不阻塞主线）。
4. **平台集**：**只做 4 平台**（抖音/快手/视频号/小红书），**不纳入 B 站**；顺手把前端 `publishModel.ts` 从 5 平台收敛到 4，与 schema 对齐。
5. **协作模式**：沿用 **Claude 架构+brief+验收 / Codex 执行写码**（`shipping-with-codex`，角色按 2026-06-18 的反向编排：Codex `task --write --cwd <worktree>` 写码、Claude 独立验收 + 提交、strip 掉 Codex 的 worktree 工件如 `package.json --configLoader`）。
6. **登录可驱动性 = 必达目标**（非锦上添花）：多客户多账号规模化不可能靠运营去小V猫 GUI 逐个扫码，故 PR0 必须全力打通"经 CDP 在自家 dashboard 驱动小V猫加号/重登/抓码/轮询 isLogin"；§4 降级方案仅作 PoC 万一失败的临时兜底，不作为终态。
