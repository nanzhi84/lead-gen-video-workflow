# 发布迁移（自研 Playwright → CDP 驱动小V猫）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> 设计依据：`docs/superpowers/specs/2026-06-19-publishing-xiaovmao-cdp-migration-design.md`（已评审，6 项决策锁定）。

**Goal:** 删除至今未启用的自研 Playwright 多平台发布，改为经 CDP 驱动小V猫桌面端发布，小V猫成为账号/登录/会话唯一事实源，登录 UX 仍留在自家 dashboard。

**Architecture:** 三条通路——(1) 发布：恢复被删的 `xiaovmao_cdp.py`，以 `XiaoVmaoPublishAdapter`（`adapter_id="xiaovmao.cdp"`）接回 `_PUBLISH_ADAPTERS`，经 CDP（`127.0.0.1:9222`）把成片+文案注入小V猫表单；(2) 账号：经 `CatBridge.getAllAccounts` 实时读，本地 `publish_accounts` 行降级为绑定锚点；(3) 登录：后端经 CDP 驱动小V猫"加号/重登"、抓码推回 dashboard、轮询 `isLogin`。承载 CDP 的进程与小V猫同机（Mac Mini）。

**Tech Stack:** Python 3.12（FastAPI + 同步发布路径，**无 Temporal worker 参与发布**）· `websockets`（CDP）· Alembic（迁移单链）· React/Vite（dashboard）· contract-first（OpenAPI 唯一事实源）。

## Global Constraints

- **承载 CDP 的进程与小V猫同机 Mac Mini**；CDP host/port 经 env `CUTAGENT_XIAOVMAO_CDP_HOST`（默认 `127.0.0.1`）/`CUTAGENT_XIAOVMAO_CDP_PORT`（默认 `9222`）。
- **只做 4 平台**：抖音 douyin / 快手 kuaishou / 视频号 shipinhao / 小红书 xiaohongshu。**不纳入 B 站**。
- **小V猫 = 账号/登录/会话唯一事实源**：平台登录态**绝不**进 SecretStore/DB。
- **诚实失败铁律**：真机未验证处显式 `XiaoVmaoUnavailableError` / 显式失败，**绝不伪造发布成功**。
- **Contract-first**：改 API 形状必须 `python scripts/export_openapi.py && (cd apps/web && npm run generate:api)` 重生成 `apps/web/src/api/openapi.json` + `schema.d.ts`（CI `git diff --exit-code` 守卫）。`schema.d.ts` 是生成物禁手改。
- **迁移**只放 `packages/core/storage/alembic/versions/`，单一线性 head（当前 `0016_finished_video_number`）。
- **ruff** line-length 100。默认测试 `python -m pytest -q`（内存后端，`conftest` 置 `CUTAGENT_ALLOW_SANDBOX_FALLBACK=1`）。
- **协作模式**：Claude 架构+brief+验收，Codex 执行写码（`shipping-with-codex`）。**在独立 git worktree 干活**（非主 checkout，非 `.claude/worktrees/` 下，node_modules symlink 主 checkout）。
- **worktree 内跑 pytest/export_openapi 先剔除 `_Finder`**：`sys.meta_path=[f for f in sys.meta_path if type(f).__name__!='_Finder']; sys.path.insert(0, WT)`（可复用 `$CLAUDE_JOB_DIR/tmp/wt_pytest.py`）。**勿** `pip install -e <worktree>`（污染共享 .venv）。

---

## PR 路线总览

| PR | 目标 | 依赖 | 本计划详度 |
|---|---|---|---|
| **PR0** | 小V猫 CDP 登录可驱动性 Spike | 需 Mac Mini + 小V猫 v2.0.0 起 9222 | 探索协议（非 TDD） |
| **PR1** | 删自研 Playwright footprint（纯减法） | 无（纯仓库内） | **完整 TDD** |
| **PR2** | 恢复 + 注册 CDP 发布 adapter（包级） | 无（mock CDP 可测） | **完整 TDD** |
| **PR3** | 迁移 0017 + API 集成 + 账号事实源切换 | PR1+PR2 合并 | 范围清单（落地前细化） |
| **PR4** | 登录通路（dashboard 驱动小V猫登录） | PR0 结论 + PR3 | 范围清单（PR0 后细化） |
| **PR5** | 前端收口 + Mac Mini 真机联调 | PR2-4 | 范围清单 |

> PR1 与 PR2 可并行（互不碰文件）。PR0 与 PR1/PR2 并行（PR0 在 Mac 上探索、PR1/PR2 在仓库内推进）。PR3-5 的逐步 TDD 任务在 PR1/PR2 合并、PR0 回报后由本计划增补——避免对 PR0 未定结论写投机代码。

---

## PR0 — 小V猫 CDP 登录可驱动性 Spike（探索，非 TDD）

**性质**：逆向真小V猫桌面端，不是写产品代码；产出"登录能否经 CDP 驱动"的结论 + 可复用样例，gating PR4 设计。**需操作员先备好环境，本机（WSL/Linux）无法替代。**

**操作员前置（Mac Mini）**
- [ ] 安装小V猫 v2.0.0（`baoteyun.com/vcat`），登录小V猫自身账号。
- [ ] 带调试端口启动：`open -a 小V猫 --args --remote-debugging-port=9222`（或对 Electron 二进制传 `--remote-debugging-port=9222`）。
- [ ] 浏览器访问 `http://127.0.0.1:9222/json/list` 确认能列出 target（含小V猫主页 `.../Resources/app/index.html`）。
- [ ] 至少在小V猫里手动添加 1 个平台账号（任意平台），供"读账号"验证。

**Spike 验证三问（对照 spec §4，每问产出结论 + 证据）**
- [ ] **Q1 读账号**：经 CDP `Runtime.evaluate` 跑 `window.CatBridge.getCall('AccountManager.getAllAccounts')`，确认返回账号数组（含 `isLogin`/`platform`/`uid`/`nickname`）。→ 复用已恢复的 `xiaovmao_cdp.py::_READ_ACCOUNTS_JS`。
- [ ] **Q2 触发登录 + 抓码**：探测 `CatBridge` 是否有 `AccountManager.addAccount`/`login`/`relogin` 类方法（`Object.keys` 枚举 bridge / 抓小V猫"添加账号"按钮的点击事件）；触发后小V猫内置浏览器打开平台登录页——定位二维码所在 CDP target/iframe/`<img>`，用 `Page.captureScreenshot` 或读 `<img>` data-url。**记录**：bridge 方法名、二维码 target 定位法、4 平台是否一致。
- [ ] **Q3 判定登录成功**：扫码后轮询 `getAllAccounts` 的 `isLogin` 是否翻 `true`、新账号是否出现。记录轮询间隔与时延。

**决策门（产出写回 spec §4 / 本计划 PR4 节）**
- [ ] **成功** → PR4 实现"dashboard 内驱动小V猫登录抓码"，记录 bridge 方法名/抓码选择器/4 平台差异。
- [ ] **部分/失败** → PR4 先落临时兜底（运营 GUI 登录 + dashboard 只读 isLogin 健康），并记录卡点继续攻关（决策 6：不接受长期 GUI 登录为终态）。

**交付**：`docs/superpowers/specs/` 下追加 `2026-06-19-xiaovmao-cdp-login-spike-findings.md`（bridge API 形状、抓码法、isLogin 轮询、4 平台差异、决策门结论）。

---

## PR1 — 删自研 Playwright footprint（纯减法）

**净效果**：删 ~1217 行自研浏览器自动化；`select_adapter()` 对所有 id 退回 `SandboxPublishAdapter`（发布暂为诚实 no-op），`select_browser_driver()` 退回 `SandboxBrowserDriver`（QR 登录走占位）。apps/api 仍干净导入（`select_browser_driver`/`PublishLoginRegistry` 仍在）。

**Files:**
- Modify: `packages/publishing/platform_adapter.py`（删 `BrowserPublishAdapter` L130-387 + 注册表去 `"browser.playwright"` L393）
- Delete: `packages/publishing/browser/playwright_driver.py`、`packages/publishing/browser/platforms.py`
- Modify: `packages/publishing/browser/driver.py`（删 `PLAYWRIGHT_BROWSER_DRIVER` 常量 L25 + `select_browser_driver` 懒导入分支 L113-116）、`packages/publishing/browser/__init__.py`（去 `PLAYWRIGHT_BROWSER_DRIVER` 导出）
- Modify/Test: `tests/publishing/test_platform_adapter.py`（删 browser 用例）、`tests/publishing/test_browser_driver.py`（删 playwright 用例）
- Delete: `tests/publishing/test_playwright_driver_platforms.py`
- Modify: `pyproject.toml`（删 `playwright` 依赖）

**Interfaces:**
- Produces: `_PUBLISH_ADAPTERS = {SANDBOX_ADAPTER_ID: SandboxPublishAdapter}`（仅 sandbox）；`select_browser_driver(explicit=None) -> SandboxBrowserDriver`（恒返回 sandbox，CDP driver 留待 PR4）；`PublishPlatformAdapter`/`PublishPayload`/`PublishOutcome`/`SandboxPublishAdapter`/`resolve_adapter_id`/`select_adapter` 签名不变。
- Consumes: 无（纯删）。

### Task 1: 删 BrowserPublishAdapter + 修 test_platform_adapter

- [ ] **Step 1: 先确认现状测试全绿（基线）**

Run: `cd <worktree> && python -m pytest tests/publishing/test_platform_adapter.py -q`
Expected: PASS（删之前的基线）。

- [ ] **Step 2: 删 platform_adapter.py 里的 BrowserPublishAdapter 与注册**

`packages/publishing/platform_adapter.py`：删除整个 `class BrowserPublishAdapter`（当前 L130-387，含 `_failure`/`_publish_douyin`/`_publish_shipinhao`/`_publish_kuaishou`/`_publish_xiaohongshu`/`_fill_first_available`）。把注册表改回仅 sandbox：

```python
_PUBLISH_ADAPTERS: dict[str, Callable[[], PublishPlatformAdapter]] = {
    SANDBOX_ADAPTER_ID: SandboxPublishAdapter,
}
```

并把模块 docstring 里描述 `BrowserPublishAdapter` 的段落（L9-13）删去。`PublishPayload` 的 `storage_state_json`/`video_path` 字段**暂留**（run_item_publish 仍用；PR3 清理）。`pathlib.Path` import 若无其它使用则一并删（grep 确认）。

- [ ] **Step 3: 改 test_platform_adapter.py——删 browser 相关**

`tests/publishing/test_platform_adapter.py`：删 import `BrowserPublishAdapter`（L12 附近）与 `from packages.publishing.browser import playwright_driver`（L11）；删 fake 类 `_FakeLocator/_FakePage/_FakeContext/_FakeBrowser/_FakeChromium/_FakeAsyncPlaywright`（L23-75）；删全部 `test_browser_adapter_*` 用例（L138-258）。保留 `test_resolve_adapter_id_*`/`test_select_adapter_*`/`test_sandbox_adapter_*`（L78-135）。顶部 `import asyncio, sys, types` 若不再使用则删。

- [ ] **Step 4: 跑测试验证绿**

Run: `python -m pytest tests/publishing/test_platform_adapter.py -q`
Expected: PASS（仅 sandbox + resolve/select 用例）。

- [ ] **Step 5: Commit**

```bash
git add packages/publishing/platform_adapter.py tests/publishing/test_platform_adapter.py
git commit -m "refactor(publishing): 删 BrowserPublishAdapter，发布退回 sandbox no-op (PR1/6)"
```

### Task 2: 删 browser/playwright_driver + platforms，修 driver/__init__/测试

- [ ] **Step 1: 删两个文件**

```bash
git rm packages/publishing/browser/playwright_driver.py packages/publishing/browser/platforms.py
git rm tests/publishing/test_playwright_driver_platforms.py
```

- [ ] **Step 2: 改 browser/driver.py——去 Playwright 分支**

`packages/publishing/browser/driver.py`：删常量 `PLAYWRIGHT_BROWSER_DRIVER = "playwright"`（L25）。`select_browser_driver` 改为恒返回 sandbox（删懒导入分支 L113-116）：

```python
def select_browser_driver(explicit: str | None = None) -> BrowserSessionDriver:
    """Select a browser driver. Only the sandbox driver exists until the 小V猫
    CDP driver lands (PR4); any explicit/env selection degrades to sandbox."""
    return SandboxBrowserDriver()
```

`resolve_browser_driver_id` 保留（仍读 env，仅不再据此导入 playwright）。

- [ ] **Step 3: 改 browser/__init__.py——去 PLAYWRIGHT_BROWSER_DRIVER 导出**

`packages/publishing/browser/__init__.py`：从 import 与 `__all__` 去掉 `PLAYWRIGHT_BROWSER_DRIVER`。其余导出（`BrowserSessionDriver`/`LoginHandle`/`LoginPollResult`/`SessionCheck`/`SandboxBrowserDriver`/`SANDBOX_BROWSER_DRIVER`/`browser_unavailable`/`resolve_browser_driver_id`/`select_browser_driver`/`LoginSession`/`PublishLoginRegistry`）不变。

- [ ] **Step 4: 修 test_browser_driver.py**

先读 `tests/publishing/test_browser_driver.py`，删任何引用 `PLAYWRIGHT_BROWSER_DRIVER` / `PlaywrightBrowserDriver` / 选 playwright 分支的用例，保留 `SandboxBrowserDriver` 的 begin/poll/validate/close 用例与 `select_browser_driver` 默认 sandbox 断言。

- [ ] **Step 5: 全 grep 确认无残留引用**

Run: `grep -rn "playwright_driver\|PlaywrightBrowserDriver\|PLAYWRIGHT_BROWSER_DRIVER\|browser.platforms\|browser\.playwright" packages apps tests`
Expected: 仅可能命中 settings 文档/无关 creative 抓取（`reference_*`），**packages/publishing 与 apps/api 下零命中**。若 apps/api 有命中需在 PR3 处理，PR1 至少保证 import 不断。

- [ ] **Step 6: 跑 publishing 套件 + apps/api 导入冒烟**

Run: `python -m pytest tests/publishing -q && python -c "import apps.api.app"`
Expected: PASS；`import apps.api.app` 无 ImportError。

- [ ] **Step 7: Commit**

```bash
git add -A packages/publishing/browser tests/publishing
git commit -m "refactor(publishing): 删自研 Playwright 浏览器登录 driver/platforms (PR1/6)"
```

### Task 3: 摘除 playwright 依赖 + 全量门禁

- [ ] **Step 1: pyproject.toml 删 playwright**

`pyproject.toml`：从依赖区删 `playwright`（仅删此包行；`websockets` 在 PR2 加）。

- [ ] **Step 2: 确认全仓无 playwright 生产引用**

Run: `grep -rn "import playwright\|from playwright" packages apps`
Expected: **零命中**（creative 的 `reference_*` 若曾用 playwright 需单独确认——它属对标抓取非发布，若命中则保留依赖并仅注释说明，不在本 PR 删依赖）。

> ⚠️ 决策点：若 `packages/creative/reference_*` 仍 `import playwright`（对标视频抓取），则 **不删** pyproject 的 playwright，仅在本 PR 注释"发布侧已不用 playwright"。执行时先 grep 决定。

- [ ] **Step 3: 全量默认套件 + ruff**

Run: `python -m pytest -q && ruff check packages/publishing apps/api`
Expected: PASS / no lint errors。

- [ ] **Step 4: Commit + 开 PR**

```bash
git add pyproject.toml
git commit -m "chore(publishing): 摘除发布侧 playwright 依赖 (PR1/6)"
```

---

## PR2 — 恢复 + 注册 CDP 发布 adapter（包级，mock CDP 可测）

**净效果**：`packages/publishing` 出现可选的 `XiaoVmaoPublishAdapter`（`adapter_id="xiaovmao.cdp"`），`CUTAGENT_PUBLISH_ADAPTER=xiaovmao.cdp` 时选中；小V猫不在时显式 `XiaoVmaoUnavailableError`、不伪造。**不碰 API service 层**（API 集成在 PR3）。

**Files:**
- Modify: `packages/publishing/platform_adapter.py`（补回 3 个 `XIAOVMAO_*` 常量 + 新增 `XiaoVmaoPublishAdapter` + 注册）
- Create: `packages/publishing/connectors/__init__.py`、`packages/publishing/connectors/xiaovmao_cdp.py`（从 git 恢复）
- Modify: `packages/publishing/__init__.py`（导出 CDP adapter 入口）
- Create/Test: `tests/publishing/test_xiaovmao_cdp.py`
- Modify: `pyproject.toml`（加 `websockets>=12`）

**Interfaces:**
- Consumes: `match_account`（`account_matching`，纯函数，恢复文件已 import）；`PlatformAccount`（`packages.core.contracts`）。
- Produces:
  - 常量 `XIAOVMAO_ADAPTER_ID = "xiaovmao.cdp"`；`XIAOVMAO_PLATFORM_KEY_MAP`（generic→小V猫 key）；`XIAOVMAO_PLATFORM_NAME_MAP`（generic→中文名）。
  - `probe_xiaovmao_accounts(*, host, port, account_group=None, case_name=None) -> tuple[list[PlatformAccount], bool, str|None]`
  - `publish_via_xiaovmao(payload: PublishPayload, *, host, port) -> PublishOutcome`
  - `class XiaoVmaoPublishAdapter`（`adapter_id="xiaovmao.cdp"`，`probe_accounts`/`publish` 满足 `PublishPlatformAdapter`，host/port 从 env 取默认）。

### Task 1: 补回 XIAOVMAO 常量 + 恢复 connectors/xiaovmao_cdp.py

- [ ] **Step 1: 在 platform_adapter.py 补回常量**（取自 `git show f4baeee^:packages/publishing/platform_adapter.py`，**只取 4 平台**）

```python
# 小V猫 CDP adapter 常量（恢复自 PR1 删除前，去掉 bilibili —— 只做 4 平台）
XIAOVMAO_ADAPTER_ID = "xiaovmao.cdp"
XIAOVMAO_PLATFORM_KEY_MAP = {
    "douyin": "Douyin",
    "kuaishou": "KuaiShou",
    "shipinhao": "Channels",
    "xiaohongshu": "XiaoHongShu",
}
XIAOVMAO_PLATFORM_NAME_MAP = {
    "douyin": "抖音",
    "kuaishou": "快手",
    "shipinhao": "视频号",
    "xiaohongshu": "小红书",
}
```

- [ ] **Step 2: 恢复 connectors 包 + CDP 文件**

```bash
mkdir -p packages/publishing/connectors
printf '"""小V猫 CDP connectors."""\n' > packages/publishing/connectors/__init__.py
git show f4baeee^:packages/publishing/connectors/xiaovmao_cdp.py > packages/publishing/connectors/xiaovmao_cdp.py
```

（或从备份 `/home/nanzhi/.claude/jobs/2ec9e4f9/tmp/xiaovmao_cdp.py` 复制。）该文件 import `XIAOVMAO_ADAPTER_ID/XIAOVMAO_PLATFORM_KEY_MAP/XIAOVMAO_PLATFORM_NAME_MAP`（Step 1 已补）、`match_account`、`PlatformAccount`。**PR2 只保留"读账号 + 发布"路径**（`XiaoVmaoDriver`/`_read_accounts`/`_drive_publish`/`probe_xiaovmao_accounts`/`publish_via_xiaovmao`）；登录驱动留 PR4 增补。host/port 默认 `127.0.0.1`/`9222`，但要支持从 env 读（见 Task 2）。

- [ ] **Step 3: 视频字段对齐**：`_drive_publish` 用 `payload.video_uri` 作本地视频路径喂 `set_files_by_index`。确认 `PublishPayload.video_uri` 存在（在）。**记录**：PR3 API 集成时须把"下载到 Mac 本地的成片路径"写入 `video_uri`（type-consistency：CDP 读 `video_uri`，不是 `video_path`）。

- [ ] **Step 4: 导入冒烟**

Run: `python -c "from packages.publishing.connectors.xiaovmao_cdp import probe_xiaovmao_accounts, publish_via_xiaovmao, XiaoVmaoUnavailableError; print('ok')"`
Expected: 打印 `ok`（`websockets` 懒 import，未装也应能 import 模块）。

### Task 2: XiaoVmaoPublishAdapter + 注册 + 导出（mock CDP 单测）

- [ ] **Step 1: 写失败测试** `tests/publishing/test_xiaovmao_cdp.py`

```python
import packages.publishing.connectors.xiaovmao_cdp as cdp
from packages.publishing.platform_adapter import (
    XIAOVMAO_ADAPTER_ID, PublishPayload, XiaoVmaoPublishAdapter, select_adapter,
)


def test_select_xiaovmao_adapter(monkeypatch):
    monkeypatch.setenv("CUTAGENT_PUBLISH_ADAPTER", "xiaovmao.cdp")
    adapter = select_adapter()
    assert isinstance(adapter, XiaoVmaoPublishAdapter)
    assert adapter.adapter_id == XIAOVMAO_ADAPTER_ID


def test_publish_unavailable_when_app_down(monkeypatch):
    # 小V猫未起 → 显式失败，不伪造成功
    def boom(payload, *, host, port):
        raise cdp.XiaoVmaoUnavailableError("小V猫未运行")
    monkeypatch.setattr(XiaoVmaoPublishAdapter, "_publish", staticmethod(boom), raising=False)
    outcome = XiaoVmaoPublishAdapter().publish(PublishPayload(title="t", platforms=("douyin",)))
    assert outcome.success is False
    assert "小V猫" in (outcome.error_message or "")
```

- [ ] **Step 2: 跑测试看红**

Run: `python -m pytest tests/publishing/test_xiaovmao_cdp.py -q`
Expected: FAIL（`XiaoVmaoPublishAdapter` 未定义）。

- [ ] **Step 3: 在 platform_adapter.py 实现 adapter + 注册**

```python
@dataclass
class XiaoVmaoPublishAdapter:
    """经 CDP 驱动小V猫桌面端发布。小V猫不可达时显式失败，绝不伪造。"""

    adapter_id: str = XIAOVMAO_ADAPTER_ID

    def _host_port(self) -> tuple[str, int]:
        host = os.getenv("CUTAGENT_XIAOVMAO_CDP_HOST", "127.0.0.1")
        port = int(os.getenv("CUTAGENT_XIAOVMAO_CDP_PORT", "9222"))
        return host, port

    def probe_accounts(self, *, account_group=None, case_name=None):
        from packages.publishing.connectors.xiaovmao_cdp import probe_xiaovmao_accounts
        host, port = self._host_port()
        return probe_xiaovmao_accounts(host=host, port=port, account_group=account_group, case_name=case_name)

    def publish(self, payload: PublishPayload) -> PublishOutcome:
        from packages.publishing.connectors.xiaovmao_cdp import (
            XiaoVmaoUnavailableError, publish_via_xiaovmao,
        )
        host, port = self._host_port()
        try:
            return publish_via_xiaovmao(payload, host=host, port=port)
        except XiaoVmaoUnavailableError as exc:
            return PublishOutcome(
                success=False, adapter_id=self.adapter_id,
                results=[{"success": False, "error": str(exc)}],
                error_message=str(exc),
            )
```

并注册：

```python
_PUBLISH_ADAPTERS: dict[str, Callable[[], PublishPlatformAdapter]] = {
    SANDBOX_ADAPTER_ID: SandboxPublishAdapter,
    XIAOVMAO_ADAPTER_ID: XiaoVmaoPublishAdapter,
}
```

> 注：测试 Step 1 用 `_publish` 替身——实现里把 `publish_via_xiaovmao` 调用抽一个 `staticmethod _publish` 以便 monkeypatch；或直接 monkeypatch `cdp.publish_via_xiaovmao`。执行者二选一，保持测试与实现一致（type-consistency）。

- [ ] **Step 4: 导出**

`packages/publishing/__init__.py`：从 `platform_adapter` 加导出 `XIAOVMAO_ADAPTER_ID`、`XiaoVmaoPublishAdapter`，并 append 到 `__all__`。

- [ ] **Step 5: 跑测试看绿 + 全 publishing 套件**

Run: `python -m pytest tests/publishing/test_xiaovmao_cdp.py tests/publishing -q`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add packages/publishing/platform_adapter.py packages/publishing/connectors packages/publishing/__init__.py tests/publishing/test_xiaovmao_cdp.py
git commit -m "feat(publishing): 恢复 CDP 驱动小V猫发布 adapter (xiaovmao.cdp) (PR2/6)"
```

### Task 3: websockets 依赖 + 全量门禁

- [ ] **Step 1: pyproject.toml 加 websockets**

`pyproject.toml` 依赖区加 `websockets>=12`。

- [ ] **Step 2: 全量默认套件 + ruff**

Run: `python -m pytest -q && ruff check packages/publishing`
Expected: PASS。

- [ ] **Step 3: Commit + 开 PR**

```bash
git add pyproject.toml
git commit -m "chore(publishing): 加 websockets 依赖供 CDP 连接 (PR2/6)"
```

---

## PR3 — 迁移 0017 + API 集成 + 账号事实源切换（范围清单，PR1+PR2 合并后细化）

**目标**：让发布真正经 CDP 走小V猫，账号读自小V猫，删自研会话存储。落地前增补逐步 TDD。

**范围（精确 file/symbol，disposition 见 spec §6/§8）**
- **迁移**：新增 `packages/core/storage/alembic/versions/0017_drop_publish_account_session_cols.py`（`down_revision="0016_finished_video_number"`）：`drop_column` `session_secret_ref`/`session_status`/`session_expires_at`/`last_validated_at`；`add_column` `xiaovmao_uid`（String nullable）。同步 `packages/core/storage/database.py` `PublishAccountRow`。
- **契约**：`packages/core/contracts/publish_accounts.py` `PublishAccount` 去 `session_status`/`has_session`/`session_expires_at`/`last_validated_at`，加 `login_status`（live isLogin，list 时计算）+ `xiaovmao_uid`。`publishing.py` 契约去 `storage_state_json`。→ **重生成 openapi.json + schema.d.ts**。
- **删**：`packages/publishing/account_sessions.py`（整文件）、`apps/api/services/publish_accounts.py::set_account_session`。
- **GUT**：`accounts_repository.py`（删 `set_account_session`/`get_account_session_ref`，加 `xiaovmao_uid` 读写）、`accounts_mappers.py`（account 映射改 live 态）、`publish_executor.run_item_publish`（去 `resolve_session→storage_state`，缺会话改判 isLogin）、`apps/api/services/publishing.py`（`_build_publish_runner` 去 SecretStore 会话 + `select_adapter` 默认走 `xiaovmao.cdp`、`resolve_video` 下成片到 Mac 本地写入 `video_uri`；`_active_publish_targets` 去 `session_status` 门禁；`platform_accounts` 改读小V猫）、`apps/api/app.py` + `common.py`（lifespan 装配 CDP，去 playwright driver）。
- **测试**：GUT `test_publish_executor.py`/`test_accounts_repository.py`/`test_publish_login.py`（会话断言）；KEEP `test_publishing_funnel.py`/`test_case_publishing_ops.py`（sandbox）。
- **门禁**：迁移 up/down round-trip；契约矩阵（`tests/contract`）绿；无 openapi/schema 漂移。

---

## PR4 — 登录通路（范围清单，PR0 结论后细化）

**目标**：dashboard QR 登录/重登底层改为经 CDP 驱动小V猫（决策 6 必达）。
- **依赖 PR0 结论**：bridge 登录方法名 / 抓码 target 定位 / isLogin 轮询。
- **GUT** `apps/api/services/publish_login.py`：`begin_login`→CDP 触发小V猫加号抓码；`poll_login`→轮询小V猫 isLogin；`validate_session`→读 isLogin；`cancel_login`→结束 CDP 引导。保留 router 入口签名。删 `publish_browser_driver`/`store_account_session`/`secret_store` 调用。
- **ADAPT** `packages/publishing/browser/driver.py`（新增小V猫 CDP `BrowserSessionDriver` 实现，去 `LoginPollResult.storage_state_json`）、`login_registry.py`（完成判定改 isLogin）。
- 在 `connectors/xiaovmao_cdp.py` 增补登录驱动函数（PR0 验证的方法）。
- **兜底**（PR0 失败时）：`begin_login` 返回"请在小V猫 GUI 完成登录"提示，`poll_login` 只读 isLogin。
- **测试**：mock CDP 的 login/poll/validate 单测 + QR 三件套集成测试改断言。

---

## PR5 — 前端收口 + Mac Mini 真机联调（范围清单）

- **ADAPT** `PublishOpsPage.tsx`（账号改小V猫拉、health 用 isLogin、加"小V猫连接状态"）、`PublishCenterPage`/`PublishReviewStep`（沙盒文案改"经小V猫发布"）、`api/client.ts`（`publishOps` GUT、删死方法 `platformAccounts`）。
- **KEEP** `QrLoginDialog.tsx`（二维码来源改抓小V猫，UX 不变）。
- 统一 `publishModel.ts` 平台集为 **4 平台**（删 bilibili）与 schema 对齐。
- **真机验收**：Mac Mini 小V猫带 9222 起、账号已登录 → 提交 case → 小V猫表单被正确填充并发出；4 平台逐一验证；UNVERIFIED 处显式失败不伪造。
- **门禁**：`npm run build` exit 0；无契约漂移；`scripts/ci_gate.sh` 绿。

---

## Self-Review（已执行）

- **Spec 覆盖**：spec §5 删除→PR1；§3.2 发布通路→PR2；§3.3 账号源+§8 迁移/契约→PR3；§3.4 登录→PR4；§6 前端→PR5；§4 PoC→PR0。全覆盖。
- **Placeholder**：PR0/PR1/PR2 为完整可执行步骤；PR3-5 显式标注"落地前细化"且给出精确 file/symbol+依赖，非含糊占位（符合 PR 依赖结构，避免对 PR0 未定结论写投机代码）。
- **Type 一致性**：CDP 读 `payload.video_uri`（非 `video_path`）—— PR2 Task1 Step3 与 PR3 `resolve_video` 已对齐记录；`XiaoVmaoPublishAdapter._publish` 替身点 PR2 Task2 已注明实现须与测试一致；`select_browser_driver` 签名 PR1 保持不变。
