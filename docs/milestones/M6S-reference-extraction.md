# M6S 施工简报：对标视频参考提取（URL→下载→ASR→口播文案）

负责：Codex（执行）/ Claude（架构 + 验收）
分支：`feat/m6s-reference-extraction`
来源：parity 审计真缺口②的 **Part A**——给一个对标视频链接，提取其口播文案/标题填入创作参考。**Part B（Playwright 自动刷 cookie）不做**——属 RPA、绑发布（M6c 冻结），归外联连接器，本批不碰。

## 已勘定事实（勿推翻）

- 原版 `backend/app/services/reference_script_extractor.py`：流程 URL → yt-dlp 取信息/字幕 → 无字幕且 <15min 则下载媒体 → ASR 转写 → 文案；douyin 走分享页 HTML 解析（`window._ROUTER_DATA` JSON）+ cookie header。**下载与流取走 HTTP（非 RPA）**；Playwright 仅用于「从浏览器抽 cookie」——本批不做这一支。
- genesis 有真 ASR 能力：`packages/ai/providers/dashscope.py` 的 `asr.transcribe`（Paraformer 异步，需公网可达音频 URL——见 M6M；本地音频需先上 OSS 取签名 URL）。有 ObjectStore（OSS）+ SecretStore + ffmpeg（packages/media/video/ffmpeg.py）。
- 创作页脚本步已有「参考」概念位（前端 StudioCreateSteps / 脚本工具条）。

## 改动清单

### A. 后端：bounded 参考提取服务（无常驻、无 RPA）

- A1 新增 `packages/creative/reference_extract.py`（或 packages/reference/）：纯函数式服务 `extract_reference(url, language="zh", *, asr_invoke, object_store, secret_store) -> ReferenceExtractResult`。
  - 用 **yt-dlp**（加进 pyproject 依赖）取 info：优先**字幕**（有就直接返回文案，省 ASR）；无字幕→下载音频（临时目录，asyncio.to_thread 包同步调用）→ 经 ObjectStore 临时上 OSS 取签名 URL → 调 genesis 现有 ASR（asr.transcribe，audio_uri=签名 URL，复用 M6M 路径）→ 文案。
  - douyin：分享页 HTML 解析 + cookie header（cookie 从 SecretStore 取，secret_ref 如 `douyin_cookie`，**一次性手工导入**，无自动刷新）。无 cookie 也尽力（公开视频）。
  - 返回 `ReferenceExtractResult(reference_script, source[subtitle|asr], title, platform, duration_sec, resolved_url)`（新契约）。失败映射清晰错误码（不可达/不支持平台/ASR 失败），不静默。
- A2 端点 `POST /api/creative/reference-extract`（operator 角色）：入 `{url, language?}` → 出上面的结果。放 `apps/api/routers/`（新 creative.py 或并入既有）。
- A3 临时下载文件用完即删（worker 本地临时目录）；上 OSS 的临时音频可走 ephemeral tier（M6O）或用完删。**不落 case 资产**（仅返回文案）。

### B. 前端（apps/web）

- B1 创作页脚本步加「对标视频提取」入口（输入链接 + 「提取」按钮）：调端点 → 把 reference_script 填进脚本参考区（或脚本草稿），title 显示来源；loading/错误 toast。沿用现有创作页风格、不回退布局。
- B2 api client + schema.d.ts 同步。

### C. 测试

- C1 服务单测：mock yt-dlp（注入 info/字幕）+ mock asr_invoke——有字幕走字幕、无字幕走「下载→上传→ASR」、douyin 分享页解析；各失败映射错误码。**不联网、不真下载**。
- C2 端点 contract test。`cd apps/web && npx tsc --noEmit && npm run build` 绿；schema.d.ts 同步。
- C3 全量基线（约 200）不回退。所有 pytest 包 `timeout -k 5 600`，主仓 venv。pyproject 加 yt-dlp（sandbox 不 pip install，验收官在外面装+live 验）。

## 边界

- **不做** Part B（cookie 自动刷新/Playwright/浏览器抽 cookie/from-browser）——归 M6c/外联。
- cookie 仅「手工导入 SecretStore」一条，本批可只留读取（导入 UI 可后续）。
- 不做小V猫发布、不碰 pipeline 真出片。

## 验收门（验收官，live）

1. 装 yt-dlp 后，给一个真实视频链接（优先有字幕的）→ 端点返回真文案/标题；无字幕的走下载+真 ASR（经 OSS 签名 URL）返回文案。
2. 前端「提取」把文案填进脚本参考。
3. 全量 + DB + Temporal + tsc/build 绿。
