# M6f 施工简报：S3 ObjectStore + 发布中心归 Case

负责：Codex（执行）/ Claude（架构 + 验收）
分支：`feat/m6f-objectstore-publish-ia`
背景：① 当前 LocalObjectStore.signed_url 原样返回 local:// URI，浏览器内成片/素材**预览播不了**（坦白②基础设施硬伤）；② 产品裁决：发布中心归属 Case，不做全局一级入口。两件都是基础设施/IA，不依赖媒体处理库，合一批。

## A. S3-compatible ObjectStore（MinIO 已就位：127.0.0.1:9000，minioadmin/minioadmin，health 200）

- A1 `packages/core/storage/object_store.py` 加 `S3ObjectStore`（boto3，需加依赖 `boto3` 到 pyproject）：
  put/get/exists/signed_url（真 presigned GET URL，浏览器可直接播）；bucket 不存在自动创建。
- A2 settings：`CUTAGENT_OBJECTSTORE_BACKEND`（local|s3，默认 local 保测试）、endpoint/bucket/access/secret
  （.env.example 已有 CUTAGENT_OBJECTSTORE_* 占位，复用）。s3 模式下 artifact 落 MinIO，signed_url 返回
  `http://127.0.0.1:9000/...?X-Amz-...` 真链接。
- A3 上传/导出/预览全链走 ObjectStore 抽象（已是）；本地 dev 仍可 local，生产/演示用 s3。
- A4 前端 toDisplayUrl 已对非 http(s) 回退占位——s3 模式返回真 http URL 后预览自然可播，无需改前端逻辑，
  但确认 preview-url/download 端点在 s3 模式返回真链。
- A5 测试：S3ObjectStore 单测用 MinIO 门控（`CUTAGENT_RUN_S3_TESTS=1`，验收官跑）；local 默认不变。

## B. 发布中心归 Case（产品裁决，docs/milestones/M6aR-frontend-redesign.md 尾部）

- B1 侧边栏移除「发布中心」一级入口（AppShell 导航项删除）。
- B2 `/publish-center` 与 `/publish-center/:batchId` 路由：重定向到 Case 选择页（或最近 Case 的发布 tab）；
  保留 Case 工作台「发布」tab 作为唯一发布形态。
- B3 批次查询强制按当前 case_id 过滤（后端 publish batches list 已支持 case_id，确认前端只传当前 case）。
- B4 跨 case 发布概览（如需）由数据统计页只读承接，不提供跨 case 操作入口。

## 边界
- 防抖/裁剪/剪映真包/模板自动匹配替换 → M6g（媒体深加工，单列）；真 portrait+HeyGem 完整真口播片
  → 等用户素材；M6c 冻结。

## Verification（sandbox 内）
- 全量 pytest 绿（基线含 M6d-fix）；`cd apps/web && npx tsc --noEmit && npm run build` 绿；
  S3 单测门控默认 skip；OpenAPI 无意外变化。

## 验收门（验收官）
1. s3 模式起服务：上传素材 → 预览-url 返回 MinIO presigned，浏览器/curl 能下到真文件；
   提交 run 出片 → 成片 preview 浏览器可播（Playwright 截图或 curl 下载校验）。
2. 发布中心：侧边栏无全局入口；/publish-center 重定向；Case 工作台发布 tab 正常；批次按 case 过滤。
3. 全量 + DB + Temporal 三套绿。

---

## 验收记录（2026-06-12，验收官：Claude）

**判定：通过并合入**（merge 见 git log）。证据：
- 全量绿（local 默认不回退）+ S3 门控测试在真 MinIO 全绿 + 23 DB 集成绿。
- **端到端真验**：s3 模式 multipart 上传 → `object_uri=s3://cutagent-local/...` → preview-url 返回 SigV4 presigned MinIO URL → curl 下到真实字节内容。**浏览器内成片/素材预览播不了的硬伤解决**。bootstrap seed 素材也正确落 MinIO（6 个对象）。
- 发布中心归 Case：侧边栏/概览移除全局入口、/publish-center 重定向、批次按 case_id 过滤（contract test 覆盖）。

真验抓到 2 个 mock 测不出的 bug（已修）：① `_is_bucket_absent_error` 引用未定义（首次 head_bucket NameError）；② MinIO 默认 SigV2，强制 boto3 SigV4 + path addressing 后 presigned 才带 X-Amz-* 且可下载。

调用方式备忘：PUT /api/uploads/{id}/file 是 **multipart `file` 字段**（不是 raw body）。
