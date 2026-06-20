# PR0 Spike findings — 小V猫 CDP 登录可驱动性（2026-06-20 真机实测）

> 在 Mac Mini（SSH `wzm-lan`）真小V猫 v2.0.0 上实跑，经 SSH 隧道 `19222→Mac 127.0.0.1:9222`。
> 结论：**CDP 驱动小V猫整条路可行，PR4 登录通路可做稳。**

## 核心结论（逐块真机验证）

| 能力 | 结果 | 证据 |
|---|---|---|
| 小V猫允许 CDP 接入 | ✅ | `open -a 小V猫 --args --remote-debugging-port=9222` → `/json/version` 返回 Electron Chrome/144 + `webSocketDebuggerUrl` |
| CatBridge 读账号（PR2 代码） | ✅ | `probe_xiaovmao_accounts` 真机跑通；`CatBridge.getCall('AccountManager.getAllAccounts')` 成功 |
| CDP 抓二维码 | ✅ | 小V猫微信登录码 + 抖音平台码均抓到 |
| 驱动小V猫表单 | ✅ | 小V猫首次绑手机号：填手机号→点「获取验证码」→填短信码→点「绑定」全部驱动成功，**小V猫注册完成** |
| 添加平台账号 → 打开平台登录页 | ✅ | 账号管理→添加账号→选抖音→「打开登录页面添加」→ **新 CDP webview target `creator.douyin.com` 打开** |
| 扫码识别真实账号 | ✅ | 抖音认出账号（昵称「我真没招了」/LiLink） |
| 平台二次验证 | ✅ 可驱动 | 抖音身份验证弹窗、「接收短信验证码」、发码均驱动成功 |

## CatBridge API 面（renderer 全局 `window.CatBridge`）
`getCall`(RPC 调度，`getCall('<Manager>.<method>')`)、`getValue`、`addListenter`+`removeListener`（**事件订阅——可监听登录成功，比轮询 isLogin 更准**）、`getReady`、`showDevtools`、`handle`、`getPathForFile`。主页面 url 末尾 `/Resources/app/index.html`（`choose_main_target` 据此选主 target）。

## 登录是两层
1. **小V猫自身**：微信扫码登录 + 首次绑手机号(短信验证码)。一次性（会话由小V猫维持 60 天）。
2. **平台账号**：账号管理 → 添加账号(平台选择弹窗，含抖音/视频号/快手/小红书/…) → 选平台 → 「打开登录页面添加」→ 平台登录页作为**新 webview target** 打开 → 平台二维码出现 → 运营扫 → 小V猫自动识别入库（几秒~十几秒）。

## 抓二维码的稳妥姿势（重要）
**取页面二维码 `<img>` 的 `src`（`data:image/png;base64,...`）直接 base64 解码成 PNG**，而**不要**对 webview 截图再裁剪——webview 是 Retina/缩放渲染，`getBoundingClientRect` 的 CSS px 与 `Page.captureScreenshot` 的 clip 对不齐，会裁出"双码/错位"。`data:image` 解出来就是页面那张原生码、单张清晰。
- 找码：`img` 中 `src` 以 `data:image` 开头、宽 110–300、近正方、可见、取最上面一个。
- 失效刷新：检测 body 含「失效/过期」→ 点二维码中心(刷新按钮)或 `Page.reload`。

## 平台风控（落地必须正视）
抖音对**新环境（这台 Mac）首登**强制**身份验证(短信验证码)** + **二维码秒级过期**；识别到账号后可能再要二次安全验证。落地启示：
- **首登用住宅 IP + 受信环境**（小V猫支持账号级独立代理 IP）能大幅降风控。
- PR4 登录链路必须**内置鲁棒处理**：二维码失效自动刷新/reload、识别并向运营透传平台二次验证步骤、轮询 `getAllAccounts` 的 `isLogin` 判完成（或监听 CatBridge 事件）。
- 规模化目标：运营在 dashboard 扫码即可，**不接触 Mac**；首登过风控后会话由小V猫维持。

## "定位要准"——盲驱动 UI 的硬教训（PR4 必须照此实现）
- **`el.click()` 不可靠**：常打到无 handler 的内层 `span`/`wrapper`，不触发。**改用 `Input.dispatchMouseEvent`（mousePressed+mouseReleased）点元素 bounding-rect 中心坐标**。
- **作用域要限定**：页面同时存在多个同名元素（弹窗的「请输入验证码」输入框 vs 背景登录表单的；弹窗「验证」按钮 vs 背景）。按 `offsetParent!==null`（可见）+ `getBoundingClientRect().x`（弹窗居中 x 小、背景表单 x 大）区分，**否则会把验证码填进背景表单、把按钮点到背景**（本次踩过）。
- **填值**：native value setter + 派发 `input`/`change` 事件（React 受控组件）。
- 这些鲁棒手法要固化进 `packages/publishing/connectors/xiaovmao_cdp.py` 的登录驱动函数。

## 运行拓扑（已确认）
承载 CDP 的进程与小V猫**同机 Mac Mini**，CDP 走 loopback；远程开发期我用 `ssh -fN -L 127.0.0.1:19222:127.0.0.1:9222 wzm-lan` 隧道接入（`/json/list` 返回的 ws url 已自带请求端口，经隧道直连即可）。生产由 Mac 上的发布服务本地连 `127.0.0.1:9222`。
