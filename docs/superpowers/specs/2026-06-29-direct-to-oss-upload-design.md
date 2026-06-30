# 浏览器直传 OSS 上传架构重设计（极简版 · rev6）

- 日期：2026-06-29
- 状态：**Codex 两个独立评审均已 clear（一个 APPROVED，另一个一行修复后 LGTM，已采纳）**，待你过目。已并入：rev2（人工 8 点）、rev3（Codex R1 1 P0+6 P1+3 P2）、rev4（Codex R2 1 carry-over P1 + 2 P2）、rev5（Codex R3-A APPROVED + 3 P2）、rev6（Codex R3-B 的 1 个 CI-不可见生产级 P2）。修订清单见 §12。
- 目标：把 API 从上传数据通道里**彻底**拿掉——浏览器**直传 OSS**（单条预签名 PUT，单文件硬上限 **100 MiB = 104,857,600 字节**，**不做分片**），API 只管鉴权、签名、登记、完成校验。**删除原服务端转发（proxy）链路，不留回退。后处理留在 API（不动 worker）。**

## 1. 背景与动机

现状链路「浏览器 → API 进程 → OSS」服务端转发：`prepare`（建 session + key，返回的 `upload_url` 实为 GET 预签名，浏览器忽略）→ `PUT /api/uploads/{id}/file`（整文件以 FormData 走 XHR 给 API，流到临时盘再 boto3 推 OSS）→ `complete`（API 下载对象跑 ffprobe，建 Artifact + MediaAsset/PublishPackage）。所有字节穿过 API（线上 浏览器→VPS→Mac→OSS，任一段慢/断就 502）；多文件串行、无队列/重试。本次只改"字节怎么到 OSS"，**后处理与登记逻辑原样保留在 API**。

## 2. 已验证的 OSS 能力（2026-06-29 实地冒烟，真凭据，写 `_smoke/`/`incoming/` 小对象跑完即删）

真实阿里云 OSS（`oss-cn-shanghai`，`addressing_style=virtual`）**接受 boto3 SigV4 预签名直传，零新依赖**（`boto3 1.43.36` 足够）：

| 能力 | 结果 | 本设计采用 |
|---|---|---|
| 预签名 PUT（裸 / 锁 content-type） | ✅ HTTP 200 | **是**（唯一上传方式） |
| HEAD（size/etag/content-type） | ✅ | **是**（complete 校验） |
| 服务端 `copy_object`（同桶） | ✅ content-type 经 `MetadataDirective=COPY` 保留 | **是** |
| **跨桶 `copy_object`（cutagent-dev → cutagent-materials）** | ✅ size+content-type 保留 | **是**（material 类 final 落 materials） |
| 单 PUT 的 ETag | = 整文件 MD5 | 备用弱校验 |
| 预签名分片 / POST policy | ✅（已验证） | **否** |
| `put/get/delete_bucket_cors` | ✅ 可设可还原 | **是** |
| 桶 CORS 当前状态 | ⚠️ ABSENT | **唯一缺口**：浏览器跨域直传前必须先配 |

结论：无外部阻塞，全是代码/配置层的活。

## 3. 已确认决策

| # | 决策 | 选定 |
|---|---|---|
| 1 | 凭证机制 | **预签名 URL**（现有静态 AK/SK；不引 STS/RAM） |
| 2 | 上传方式 / 大小 | **单条预签名 PUT，硬上限 100 MiB，不分片**；超限**三道闸**：前端 DropZone / `prepare` 声明校验 / `complete` HEAD（**无"签名闸"**：presigned PUT 不能像 POST policy 那样强制 content-length-range） |
| 3 | 完整性校验 | `complete` 下载对象后**复算 sha256/size 并 patch 到 upload**，再据此建 artifact（删 proxy 后这道服务端校验由 complete 承担）；客户端 `crypto.subtle` 预算 sha256 作早期校验（≤100 MiB 原生可算，**零新前端依赖**） |
| 4 | 后处理落点 | **留在 API**：complete 同步跑 ffprobe + 缩略图（+ 可选 normalize/stabilize）；**不动 worker、不引 processing 态/SSE** |
| 5 | proxy 链路 | **删除、不留回退**：移除 `PUT /api/uploads/{id}/file` + 服务端流盘转发 |
| 6 | 对象安全 | **staging→final 两键**：浏览器只 PUT 到 **durable 桶**的 staging key；complete 校验通过后服务端 `copy_object` 到按 kind 路由的 final key（material 类为 materials 桶=**跨桶**）并删 staging，杜绝"已校验对象被旧 PUT URL 覆盖" |
| 7 | 工作树基线 | 干净从 `origin/main`（`d71a487`）起新分支 |

> 连带：纯文件系统 `LocalObjectStore` 不能作浏览器直传目标。上传后端**必须可预签名的 S3 兼容端**（真实 OSS / 本地 MinIO）。后端不支持预签名时 `prepare` **显式报错、绝不静默回退**。

## 4. 目标架构

### 4.1 数据流（唯一路径）

```text
浏览器 ──POST /api/uploads/prepare {kind,case_id,filename,content_type,size_bytes,sha256?}──▶ API
  · 校验 operator 角色 / content_type ∈ 允许集(§4.5) / size_bytes ≤ 100 MiB（Pydantic le= 已挡，见 §5.2）
  · 同一 uuid 派生两键：
      staging = durable 桶 / incoming/uploads/{uuid}/{filename}   （浏览器唯一可写处）
      final   = TieredObjectStore 按 kind 路由的桶 / {kind}/{uuid}/{filename}（material 类→materials 桶）
  · 对 staging 签 PUT URL（钉死 Content-Type；TTL = CUTAGENT_UPLOAD_PRESIGN_TTL_SECONDS，默认 900s）
  · 建 UploadSession(status=prepared)；object_uri 暂存 staging uri
        ◀── PrepareUploadResponse { upload_session, put_url, put_content_type, expires_at }

浏览器 ──PUT bytes ──▶ OSS durable/staging（裸 body，带签名里的 Content-Type；无 cookie / 无 FormData）
  · XHR onprogress 驱动进度；失败整文件重试；URL 过期→重取 prepare

浏览器 ──POST /api/uploads/complete {upload_session_id, sha256?, size_bytes?, metadata}──▶ API   # 路由无 {id}，body 带 upload_session_id
  · staging_uri = upload.object_uri（先保存，后续无论走哪条路径都要删它）
  · status: prepared → uploading（patch；现有迁移，complete 必须先置 uploading）
  · HEAD staging：存在? Content-Length==size_bytes? Content-Type == upload.content_type（prepare 已校验其 ∈ 允许集）? 不符→删 staging + failed
  · 下载 staging（local_object_path）→ ffprobe → 复算 sha256/size 比对（不符 failed），patch upload.sha256
  · 可选 normalize/stabilize（沿用现逻辑；其输出本就 store_file 到 server-only 新对象）
  · 定 final：normalize/stabilize 改写过→用其输出对象；否则 copy_object(staging→final，跨桶)
  · delete(staging_uri)（无条件，覆盖两条路径）；upload.object_uri 指向 final
  · status: uploading → completed；建 Artifact(uploaded.file, sha256=复算值) + 按 kind 建 MediaAsset/PublishPackage
        ◀── CompleteUploadResponse {upload_session, artifact, media_asset?|publish_package?, request_id}   # 形状不变
```

> 与今天的差别：①字节走 浏览器→OSS；②complete 对象来自 OSS 下载；③新增 sha256 复算 + staging→final 转存 + 删 staging。probe/normalize/stabilize/登记/返回形状不变。

### 4.2 完整性与大小
- **大小三道闸**：前端 DropZone（100 MiB）；`prepare` 的 `size_bytes ≤ 100 MiB`（Pydantic `le=`）；`complete` HEAD 校验 `Content-Length`（超限→删 staging+failed）。**不依赖签名强制大小**。
- **类型**：content-type 允许集（§4.5）在 prepare 校验并焊进 PUT 签名（浏览器须发相同 Content-Type）。
- **sha256（权威在 complete）**：complete 下载后 `sha256_file` 复算，与客户端声明比对（不符 failed），并 **patch 到 `upload.sha256`** 再建 artifact（防客户端没传时 artifact 缺哈希）。客户端 `crypto.subtle.digest('SHA-256', buf)` 早期校验。

### 4.3 后处理（留在 API，逻辑不变）
- complete 沿用现有 probe/normalize/stabilize/缩略图/建 artifact+asset/package；最终对象为 §4.1 的 final key。
- 骑在已完成会话上的端点（`create_media_asset`/`replace_asset_source`/`auto_match_replace`/语音克隆）不变。
- 不引 processing 态、不动 SSE/worker/`packages/production`。

### 4.4 生命周期 / 状态机（不改状态机表）
- `UPLOAD_SESSION_TRANSITIONS`：`prepared→{uploading,failed,cancelled,expired}`、`uploading→{completed,...}`、`completed` 终态。**无 `prepared→completed`**。
- `complete` **必须显式两跳**：`patch(prepared→uploading)` → HEAD/sha256/probe/转存 → `patch(uploading→completed)`。（现 `complete_upload` 直接断言 `→completed`，依赖 proxy 的 `upload_file` 已置 `uploading`；删 proxy 后须自行先置。）
- `cancel`：HEAD+删 staging（若已 PUT）→ `→cancelled`。（现 `cancel_upload` 只 patch 状态、不碰对象存储，须补删 staging。）
- **过期/废弃清理**：浏览器 PUT 成功但 complete 未到时，staging 已有对象而 session 仍 `prepared`。清理须 `HEAD`+删 staging 对象（非只删 DB 行）；并给 durable 桶 `incoming/uploads/` 前缀配 **OSS 生命周期 TTL** 兜底。

### 4.5 Content-Type 允许集（按 UploadKind，集中为一处常量）

| UploadKind | 允许 MIME |
|---|---|
| `publish_video` / `portrait` / `broll` / `video` | `video/mp4`（核心）、`video/quicktime`、`video/webm` |
| `image` / `cover_template` | `image/png`、`image/jpeg`、`image/webp` |
| `voice_reference` / `bgm` | `audio/mpeg`、`audio/wav`、`audio/x-wav`、`audio/mp4`(m4a)、`audio/aac` |
| `font` | `font/ttf`、`font/otf`、`font/woff`、`font/woff2`（+ legacy `application/x-font-ttf`、`application/vnd.ms-opentype`） |

> 集合实现期可微调，但必须集中定义（一处常量）；prepare 据此校验，不符返回明确错误码（复用/新增 `ErrorCode.upload_unsupported_type`）。

## 5. 各层改动清单

### 5.1 对象存储层 `object_store.py` / `tiered_object_store.py`
- `ObjectStore` 基类 + `S3ObjectStore` 新增（`LocalObjectStore.supports_presign()→False`，其余预签名方法 raise/NotSupported）：
  - `supports_presign() -> bool`
  - `signed_put_url(uri, *, content_type, expires_in) -> SignedUrlResponse`（`generate_presigned_url('put_object', Params={Bucket,Key,ContentType})`）
  - `head(uri) -> {size, etag, content_type}`（升级现 `exists/head_object`）
  - `copy(src_uri, dst_uri)`：服务端 `copy_object`，`MetadataDirective="COPY"`；**src_uri 与 dst_uri 可能不同桶**——`S3ObjectStore.copy()` 从 `src_uri` 解析源桶放进 `CopySource`（不可假设 `self.bucket`），校验 `dst==self.bucket`；跨桶（dev→materials）已在真 OSS 验证。**⚠️ `copy()` 不得调 `_validate_read_ref(src_ref)`**：src 仅作 boto3 `CopySource` 参数、不经 `_read_buckets` 守卫。materials 子存储的 `_read_buckets` 只含自身（`object_store_env.py` 建 materials 时不传 read_buckets），若像 `get_bytes`/`download_file`/`exists`/`signed_url`(`object_store.py:236/264/276/287` 一贯调 `_validate_read_ref`) 那样 cargo-cult 加 `_validate_read_ref(src)`，则 `cutagent-dev ∉ {cutagent-materials}` → 抛错，**全部 7 种 material 类上传在 copy 处炸，而单桶 moto/CI 测不出**；跨桶可读由同账号 IAM 凭据保障。
  - `ensure_cors(origins, *, methods=[PUT,GET,HEAD], expose=["ETag","x-oss-request-id"])`
- **`TieredObjectStore` 必须实现/路由所有新方法**（现仅有 `prepare_upload`/`signed_url`）：
  - `supports_presign()` → 委托 durable 子存储（staging 永远落 durable）。
  - `signed_put_url(staging_uri)` → durable 子存储。
  - `head(uri)` / `copy(src,dst)` → 按 uri 的桶找对应子存储；`copy` 路由到 **dst** 子存储执行写入（src 桶仅作 CopySource，同账号可读）。
  - 确定性键派生（**不生成随机 uuid**）：**复用现有 `prepare_upload(filename, purpose, content_key=key_uuid)`**——`content_key` 参数已支持（`object_store.py:108/214`：`key_segment = content_key if content_key is not None else uuid4().hex`），**无需新增方法名**。prepare 生成一个 uuid，用它造 staging=`incoming/uploads/{uuid}/{filename}`(durable) 与 final=`{kind.value}/{uuid}/{filename}`(按 kind 路由)；complete 从 staging key 解析出同一 uuid+filename，再以同一 `content_key=uuid` 重导出 final（两键共用一个 uuid，确定性，**无新 DB 列**；final 不在 prepare 持久化，complete 重导出）。
- 写桶单一守卫保留；签名钉死 bucket+key。**不新增任何 multipart 方法。**

### 5.2 契约 `packages/core/contracts/media.py`（→ 重生成 OpenAPI + schema.d.ts）
- `PrepareUploadRequest`：删死 flag `multipart`；`size_bytes: int = Field(gt=0, le=100*1024*1024)`（Pydantic 级硬挡，两实现者一致）。
- **新增 `PrepareUploadResponse` = `{upload_session: UploadSession, put_url: str, put_content_type: str, expires_at: datetime}`**；prepare 路由 `response_model` 由 `UploadSession` 改为它。**原因（P0）**：SQLAlchemy 后端 `prepare` 经 `create_upload`→`upload_row_to_contract` 把 `UploadSession.upload_url` 冲成 `object_uri`（sqlalchemy_uploads.py:28），签名 URL 会丢；专用响应不依赖该字段。
- `CompleteUploadRequest`：`size_bytes`/`sha256` 已有，无需新增。
- 错误码：复用/新增 `upload_unsupported_type`。
- `contracts/__init__.py` 的 import + `__all__` 同步。**预计无新状态枚举。**

### 5.3 API `apps/api/{routers,services}/uploads.py`
- **删除** API 层 `PUT /api/uploads/{id}/file` 路由 + service `upload_file` + `_stream_upload_to_disk`。
  > 注意区分两层 `upload_file`：要删的是 **API service 层**；**对象存储 `S3ObjectStore.upload_file`/`upload_fileobj` 保留**（normalize/stabilize 的 `store_file`、缩略图 `put_bytes` 等服务端写仍用）。
- `prepare`：校验大小/类型/角色 → 派生 staging(durable)+final(按 kind) 双键 → `signed_put_url(staging)` → 落 session(object_uri=staging) → 返回 `PrepareUploadResponse`；后端 `not supports_presign()` → 显式报错。
- `complete`：`staging_uri=upload.object_uri` → `patch(prepared→uploading)` → `head(staging)` 校验（Content-Length==size_bytes 且 Content-Type==upload.content_type；不符删 staging+failed）→ 下载+probe+复算 sha256(patch)+可选 normalize/stabilize → 定 final（final_uri 由 staging key 里的 uuid+filename 经 `ref_for(kind.value, uuid, filename)` 确定性重导出 = `{kind}/{uuid}/{filename}` 路由到 kind 对应桶；normalize/stabilize 改写过→用其输出对象，否则 `copy(staging→final)`）→ **`delete(staging_uri)`（无条件，覆盖两条路径）** → object_uri=final → `patch(uploading→completed)` → 建 artifact(sha256=复算)+asset/package → 返回（形状不变）。
- `cancel`：parse staging_uri → `if exists: delete` → `→cancelled`。`get`：不变。

### 5.4 DB 迁移
- **预计无需迁移**：staging 经确定性键派生、`object_uri` 在 complete 内由 staging 改写为 final，复用现列；无新列、无新状态。
- 若审计确需，再补最小 `0023`（接单一 head `0022`，revision id ≤32 字符）。

### 5.5 前端 `apps/web`
- **删除** `uploadFormData` / `api.uploads.uploadFile` 的 proxy PUT 路径。
- 新直传 util：对 `put_url` 发**裸 body** XHR PUT（发 `put_content_type` 指定的 Content-Type，**不带 cookie / 不用 FormData**），`xhr.upload.onprogress` 驱动进度（复用主 checkout WIP 的 `onProgress`/`loadedBytes`/`totalBytes` 形态）；失败整文件重试（指数退避），URL 过期重取。
- 客户端 sha256：`crypto.subtle.digest('SHA-256', await file.arrayBuffer())`（≤100 MiB，无新依赖）。
- 全局上传队列：多文件**并发**（替换 `SourceStep` 串行 for-await）、每文件状态/进度/重试。
- **大小上限统一为 100 MiB 字节值**：`DropZone.maxSize` 单位经 `dropZoneModel.ts:35` 的 `maxSizeMb * 1024 * 1024` 即 **MiB**，故 `maxSize={100}` 恰为 100 MiB，与服务端 `max_size_bytes=100*1024*1024` 对齐（无需 104 凑数）。**所有 DropZone 调用方的 maxSize 不得 > 100**（否则前端放行后被服务端 422，无友好提示）。需改的：`SourceStep.tsx:149`（600→100）、`LibraryAssetUploadModal.tsx:64`（非字体 120→100，字体 40 保留）、`TemplateUploadModal.tsx:137`（500→100）。`VoiceModals.tsx`（80）与字体（40）比 100 更严，**保留即可**（前端可更严、不可更松）。
- 返回形状不变，**无 processing UX**。

### 5.6 CORS / 运维
- **只需对 durable 写桶（`cutagent-dev`/`cutagent-prod`）下发浏览器 CORS**（staging 永远落 durable，浏览器只 PUT 这里）。materials 桶仅作服务端 `copy` 目的地、无浏览器 PUT，**不需要浏览器 CORS**。
- CORS：`AllowedOrigins`=各 web 源（`https://app.shuying.cyou` + dev `http://localhost:5173` 等）、`AllowedMethods`=PUT/GET/HEAD、`AllowedHeaders=*`、`ExposeHeaders`=ETag,x-oss-request-id、`MaxAgeSeconds`。
- 幂等下发脚本（`scripts/`）+ durable 桶 `incoming/uploads/` 前缀 OSS 生命周期 TTL；文档化允许源；dev 用 MinIO 时同样下发。

### 5.7 配置 `packages/core/config/settings.py`
- `max_size_bytes` → **100 MiB**，**两处都改**：`UploadSettings` 默认值（settings.py:344）与 `build_settings` 的 env 默认（settings.py:671 `_env_int("CUTAGENT_UPLOAD_MAX_SIZE_BYTES", ...)`）。
- 新增 `presign_ttl_seconds`（env `CUTAGENT_UPLOAD_PRESIGN_TTL_SECONDS`，默认 900）、`cors_allowed_origins`（env `CUTAGENT_UPLOAD_CORS_ALLOWED_ORIGINS`）。
- 删除只服务 proxy 流盘的 `chunk_bytes`（确认无消费者后）。
- secret 仍只走 SecretStore；OSS AK/SK 仍走 `CUTAGENT_OBJECTSTORE_*`（不变）。

## 6. 安全
- 预签名 PUT URL 是 bearer 凭据：短 TTL（默认 900s），签名钉死 bucket+key+method+content-type；只能写 durable 桶的 staging key。
- staging→final：已校验 artifact 落 server-only final key，浏览器无任何可写 URL 指向它 → 防 complete 后覆盖。
- 大小：DropZone + prepare(`le=`) + complete HEAD 三道闸。
- 角色仍要求 operator；登记仍走 owner 隔离。

## 7. 错误处理与边界
- PUT 失败/超时：整文件重试；URL 过期 → 重取预签名。
- **PUT 成功但 complete 未到**：staging 有对象、session 停 `prepared` → 清理 HEAD+删 staging + OSS 生命周期 TTL 兜底。
- HEAD/sha256 不符或超限：删 staging + `failed` + 明确错误码。
- 后端不支持预签名（`LocalObjectStore`）：`prepare` 显式报错，不回退。
- 沙箱/测试：沙箱不产真实预签名 URL；单测/契约测试用 MinIO（moto/真 MinIO）或 stub。

## 8. 测试策略
- 单元：`signed_put_url`/`head`/`copy`（含跨桶）/`supports_presign`（含 Tiered 路由）（moto 或 MinIO）；prepare 大小(`le=`)+MIME 闸；complete 两跳状态 + HEAD + sha256 复算/patch + staging→final + 删 staging。
- 契约：OpenAPI/schema.d.ts 漂移闸；新增 `PrepareUploadResponse`、删 `multipart`。
- 集成（gated，真 OSS）：固化冒烟为验证配方（预签名 PUT + HEAD + 同桶/跨桶 copy_object + CORS）。
- 前端：队列并发/整文件重试、`crypto.subtle` sha256、DropZone 100 MiB 拒收、发指定 Content-Type。
- **回归（删 proxy `file` 端点必须同改：全仓 grep 确认 = 10 测试文件 + 2 契约矩阵）**：
  - **`tests/api/test_upload_object_store.py`（655 行，11 处 `/file`：行 73/108/153/316/342/381/431/470/512/561/624）——最大、最易漏的一个**。其中 `test_upload_file_rejects_size_mismatch_before_completion`(:304，断言 `upload.size_mismatch` @:320) 测的是 **proxy 服务端流式大小校验**，新设计里该行为消失，须**重新设计**为校验 complete 的 HEAD `Content-Length`（非机械替换）。**注意该用例现用 `content_type:"text/plain"`——新 prepare 的 MIME 校验会先以 `upload.unsupported_type` 拒掉它，重设计时须同时把 content_type 改为 `video/mp4`，再用 moto/MinIO 令 HEAD 返回不匹配的 Content-Length，断言 complete→`upload.size_mismatch`。**
  - 其余直接 `PUT /api/uploads/{id}/file`：`tests/api/test_media_replacement.py`(:41,:211)、`tests/api/test_annotation_batch.py`(:35)、`tests/api/test_publish_copy_cover_endpoints.py`(:45)、`tests/api/test_upload_streaming_normalize.py`(:71 起 5 处)、`tests/integration/test_sqlalchemy_auth_uploads.py`(:96)、`tests/integration/test_sqlalchemy_media_assets.py`(:46)、`tests/integration/test_sqlalchemy_publishing.py`(:52)、`tests/integration/test_sqlalchemy_voices.py`(:50)、`tests/golden/test_case_publishing_ops.py`(:69)。
  - 契约矩阵：`tests/contract/test_api_contract_matrix.py`(:26)、`tests/contract/test_openapi_matrix.py`(:16) 删 `/file` 条目。
  - 改法：集成/golden 测试改为「prepare → mock/moto 直传 staging → complete」；`test_upload_object_store` 与 `test_upload_streaming_normalize` 的"服务端流式"前提消失，改为「complete 下载后处理 / HEAD 校验」。
  - 注意：`tests/media/test_assets_store_file_streaming.py`、`tests/api/test_object_store_backends.py`/`test_object_store_materials_routing.py`/`test_object_store_tiered_s3.py`（mock `upload_file`/`upload_fileobj`）测的是**对象存储层**，该层方法保留，**不删**。

## 9. 落地顺序（一次性交付，内部分步便于评审）
1. object_store：`signed_put_url` + `head` + `copy`(含跨桶) + `ensure_cors` + `supports_presign`，并在 `TieredObjectStore` 实现/路由全部新方法（+ 单测）。
2. 契约：新增 `PrepareUploadResponse`、删 `multipart`、`size_bytes` 加 `le=`（+ 重生成 OpenAPI/schema.d.ts）。
3. API：`prepare`（双键 + 专用响应 + 大小/类型校验）+ `complete`（两跳状态 + HEAD + sha256 复算 + staging→final + 无条件删 staging）+ `cancel`（删 staging）+ **删旧 proxy `file` 端点** + 同步迁移 §8 的 ≥11 测试 + 2 矩阵。
4. 前端：直传 util + 全局并发队列 + `crypto.subtle` sha256 + 整文件重试 + DropZone/SourceStep 100 MiB + **删 proxy 路径**。
5. 配置：`max_size_bytes` 两处 → 100 MiB + `presign_ttl_seconds` + `cors_allowed_origins`。
6. CORS 下发脚本（仅 durable 桶）+ `incoming/` 生命周期 TTL + 文档 + 真 OSS 集成验证。
7. `scripts/ci_gate.sh` 全绿 → 开 PR。

## 10. 风险与缓解
| 风险 | 缓解 |
|---|---|
| 真 OSS 兼容性 | 预签名 PUT/HEAD/同桶+跨桶 copy_object/CORS 均已实地冒烟 PASS（§2），固化为集成验证 |
| 删 proxy 波及测试/调用方 | §8 已列 ≥11 测试 + 2 矩阵 + 区分对象存储层 `upload_file`（保留）；实现前再全仓 grep 一遍 |
| 跨桶 copy 写错桶/403 | `copy` 从 src_uri 解析源桶、Tiered 路由到 dst 子存储；跨桶 dev→materials 已验证 |
| normalize/stabilize 路径漏删 staging | complete 开头存 staging_uri，所有路径末尾无条件 delete |
| 大小上限单位歧义 | 统一 100 MiB 字节值；DropZone 经 dropZoneModel 已是 MiB，三处对齐 |
| 100 MiB 卡住部分成片 | 产品硬约束（用户定）；前端清晰超限提示 |
| CORS 配错→浏览器静默失败 | 仅 durable 桶下发 + 集成验证 + ExposeHeaders ETag |
| 契约漂移（CI 闸） | 改契约即重生成 openapi.json + schema.d.ts；同步 `__all__` |

## 11. 已解决（无未决项）
- 凭证=预签名 URL；上传=单 PUT、≤100 MiB、不分片；完整性=complete 复算 sha256+patch / 客户端 crypto.subtle 早校验；后处理=留在 API；对象安全=staging(durable)→final（按 kind，可跨桶）+ 无条件删 staging；proxy=删除不回退；工作树=干净从 origin/main 起。
- 不动：worker / `packages/production` / SSE / 状态机表 / （预计）DB 迁移 / 对象存储层 `upload_file`。

## 12. 评审修订（已折叠）
### rev2 — 人工评审 8 点（对照代码核实）
P0 prepare 签名 URL 被 mapper 冲掉 → `PrepareUploadResponse`（§5.2）｜P0 complete 后旧 PUT URL 可覆盖 → staging→final（§3-6/§4.1）｜P1 prepared 有残留对象 → 清理 HEAD+删 staging + TTL（§4.4/§7）｜P1 路由 `POST /api/uploads/complete`（§4.1）｜P1 complete 须 `prepared→uploading→completed`（§4.4/§5.3）｜P1 MIME 允许集（§4.5）｜P1 complete 复算 sha256+patch（§4.2/§5.3）｜P2 删"签名闸"（§3-2/§4.2）。

### rev3 — Codex 第 1 轮（1 P0 + 6 P1 + 3 P2，逐条对照代码核实）
- **P0 跨桶 copy 未定义** → §5.1 明确 `copy` 解析 src 桶、Tiered 路由 dst 子存储；**真 OSS 跨桶 copy 已实测通过**（§2）。
- **P1 normalize/stabilize 后不删 staging**（uploads.py:301-313 改写 object_uri 不删旧对象）→ complete 开头存 staging_uri、末尾无条件删（§4.1/§5.3）。
- **P1 `supports_presign` 等新方法未覆盖 `TieredObjectStore`**（生产是 Tiered）→ §5.1 要求 Tiered 实现/路由全部新方法。
- **P1 DropZone 大小单位** → 经核实 `dropZoneModel.ts:35` 用 `*1024*1024`（即 **MiB**），故 `maxSize={100}` 本就是精确 100 MiB；Codex"100 vs 104MB 拒合法文件"的前提不成立。实际动作仅：SourceStep 600→100、服务端同为 `100*1024*1024`（§5.5）。
- **P1 `cancel_upload` 不删 staging**（uploads.py:352-360 只 patch 状态）→ §4.4/§5.3 cancel 补 HEAD+删 staging，§9-3 列入。
- **P1 size_bytes 无上限 / prepare 无类型校验**（media.py:51 仅 `gt=0`；prepare 不校验）→ §5.2 `le=100*1024*1024` + §4.5 类型校验。
- **P1 删 proxy 端点波及测试**（Codex 报 6，实际 grep 出 ≥11 文件 + 2 矩阵）→ §8 完整列出 + 区分对象存储层 `upload_file` 保留。
- **P2** `max_size_bytes` 默认 2GiB 在 settings.py:344 与 :671 两处 → §5.7 两处都改。
- **P2** complete 后 `upload_url` 为裸 s3:// → 调用方不得当播放 URL 用（§5.5/§11；新 `PrepareUploadResponse` 已不靠该字段）。
- **P2** `presign_ttl_seconds` 缺 env 名 → `CUTAGENT_UPLOAD_PRESIGN_TTL_SECONDS` 默认 900（§5.7）。

### rev4 — Codex 第 2 轮（1 carry-over P1 + 2 新 P2，全仓 grep 复核）
- **P1 carry-over**：`tests/api/test_upload_object_store.py`（655 行 / 11 处 `/file`）漏在迁移清单（我 round-1 的 grep 正则过紧没匹配到，Codex 用 `.*file` 抓到，已实地复核坐实）→ §8 补全为 **10 文件 + 2 矩阵**，标注 `test_upload_file_rejects_size_mismatch_before_completion` 需重设计为 HEAD 校验（非机械替换）。
- **P2 final key 推导未写明** → §5.1/§5.3 明确 `ref_for(purpose, key_uuid, filename)` 确定性派生、final=`{kind}/{uuid}/{filename}`、complete 从 staging key 解析 uuid 重导出（不在 prepare 持久化，无新 DB 列）。
- **P2 HEAD Content-Type 语义模糊** → §4.1/§5.3 改为 `== upload.content_type`（prepare 已校验 ∈ 允许集）。
- DropZone 单位纠正：Codex 复核**确认我对**，原 round-1 finding 撤回（`dropZoneModel.ts:35` 用 `*1024*1024` 即 MiB，`maxSize={100}` 恰为 100 MiB）。

### rev5 — Codex 第 3 轮（独立全新一轮）：**VERDICT: APPROVED**，无 P0/P1
Codex 对照真实代码逐条确认前两轮问题全部解决（含 `PrepareUploadResponse` 必要性、两跳状态机、normalize/stabilize 删 staging、cancel 删 staging、§8 测试清单 10+2 完整、max_size 两处、DropZone MiB、跨桶 copy 可实现、`ErrorCode.upload_unsupported_type` 已存在、Tiered 缺 4 方法须补）。附 3 个不阻塞 P2，已折入（均经我实地核实）：
- **P2-1** 另两个 DropZone 调用方超 100（`LibraryAssetUploadModal` 120、`TemplateUploadModal` 500）也要收 100（§5.5）；并发现 `VoiceModals`(80) 更严、保留即可。
- **P2-2** 重设计的 size-mismatch 测试须把 `text/plain` 改 `video/mp4`（否则先被 MIME 校验拒）（§8）。
- **P2-3** `ref_for` 即现有 `prepare_upload(..., content_key=uuid)`，无需新增方法（§5.1）。

### rev6 — Codex 第 3 轮的第二个独立评审（catch 了 R3-A 漏掉的 1 个生产级 P2）
两个评审 agent 并行各跑一轮 rev4：一个直接 APPROVED（rev5 已收尾其 3 个 P2），另一个验证三条 R2 修复均 OK 后，多揪出一条 **CI 不可见的生产地雷**——
- **P2（已采纳，§5.1）**：`S3ObjectStore.copy()` 必须**显式不调 `_validate_read_ref(src)`**。现有所有读方法（:236/264/276/287）都调它，cargo-cult 反射强；materials 子存储 read 集只含自身，跨桶 copy 路由到 materials 执行时源桶是 dev，若误加该守卫会让 7 种 material 类上传在 copy 处全炸、而单桶 CI 全绿。已实地核实代码证据吻合。
- 该 agent 其余全扫无新发现（`chunk_bytes` 仅 `upload_file` 体内消费、complete 路由现状即 `/api/uploads/complete`、状态机两跳合法、Tiered `_store_for_ref` 支持 dst 路由、`prepare_upload` 有 `safe_name` 净化可复用）。
- **收获**：两个独立评审分头跑，diversity 多兜住一个 CI-invisible 缺陷——印证对承重项做多视角对抗评审的价值。

### 实现期修订（impl，对 §3 连带后果 / §5.1 的反转）
- **`LocalObjectStore` 改为可预签名的测试/开发替身**（原 spec 定 `supports_presign()→False`+prepare 显式报错）。原因：整个测试套件跑在内存/Local 后端（conftest `CUTAGENT_STORAGE_BACKEND=memory` + 对象存储临时目录），若 Local 报错则**所有上传测试在 prepare 第一步即失败**、Task 6 测试迁移无从落地——这是 spec 三轮评审都没抓到、接触测试装配才暴露的关键缺口（用户拍板选「Local 测试替身」）。实现：`supports_presign()→True`；`signed_put_url` 返回 `local://` URI；`head`/`copy` 本地实现；`ensure_cors` no-op；直传测试 helper 见 `local://` 就直接 `put_bytes` 写入 store（模拟浏览器→OSS，**仍无 HTTP proxy、API 不碰字节**）。生产仍走 S3/OSS。取舍：生产若误配成 local 后端不会在 prepare 硬报错（浏览器拿到不可用的 `local://` URL 才失败）——可接受，local 仅 dev/测试用。
- **前端并发队列暂缓**：`useUpload` 已改为直传（prepare→`crypto.subtle` sha256→`putToOss` 裸 body PUT→complete），但 `SourceStep` 仍按文件**串行**调用它（功能正确、API 已彻底移出数据通道）。多文件**并发队列**列为后续增强（非 CI/正确性必需）。DropZone 上限三处收到 100MiB（SourceStep/LibraryAssetUploadModal 非字体/TemplateUploadModal）。
- **CORS/lifecycle 下发是部署步骤**：`scripts/provision_oss_cors.py`（幂等）每环境跑一次才启用浏览器直传；`put_bucket_lifecycle_configuration`（`incoming/uploads/` 1 天过期）已对真 OSS 可逆冒烟确认可设可还原。gated 回归 `tests/integration/test_oss_direct_upload_real.py` 默认 skip（`CUTAGENT_RUN_OSS_TESTS=1` 开）。
- **测试迁移**：10 文件 + 2 矩阵全绿；视频类用 `generate_test_video`（ffmpeg）、音频用真 WAV、其余「只要 artifact」的用 `font`+`template_mode=replace`（免 probe/免 ffmpeg/免自动建资产）。`tests/contract/test_settings_config.py` + `.env.example` 随 100MiB/新 env 对齐。2 个 xiaovmao-CDP 状态测试在本机因 9222 端口开着假失败（主 checkout 同样、CI 通过）。
