# 浏览器直传 OSS 上传 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:executing-plans 在**当前工作树内联执行**（**不要**用 subagent-driven：本仓 Workflow/子代理的 Bash cwd 会重置回主 checkout，编辑会落错树，见记忆 workflow-agent-cwd-and-stale-base）。步骤用 `- [ ]` 跟踪。
> 依据 spec：`docs/superpowers/specs/2026-06-29-direct-to-oss-upload-design.md`（rev6，Codex 双评审 clear）。

**Goal:** 浏览器经单条预签名 PUT 直传 OSS（≤100MiB，不分片），API 只签名+登记+HEAD 校验；删除 proxy 转发链路；后处理仍在 API。

**Architecture:** `prepare` 派生 staging(durable 桶)+final(按 kind 路由) 双键、签 staging 的 PUT URL、返回 `PrepareUploadResponse`；浏览器裸 body PUT 到 OSS；`complete` 两跳状态 + HEAD 校验 + 下载复算 sha256 + 可选 normalize/stabilize + 服务端 `copy_object`(可跨桶) staging→final + 无条件删 staging + 建 artifact/asset/package。

**Tech Stack:** FastAPI + Pydantic v2；boto3（S3 兼容 OSS，**零新依赖**）；React/Vite + 浏览器原生 `crypto.subtle`/XHR；pytest；alembic（本计划**预计零迁移**）。

## Global Constraints（每个任务隐含遵守）

- 单文件硬上限 **100 MiB = 104857600 字节**；**只单 PUT、不分片**。
- **删 proxy `PUT /api/uploads/{id}/file` 不留回退**；后端无预签名能力 → `prepare` 显式报错。
- **后处理留在 API**：不动 worker/`packages/production`/SSE/状态机表/DB 迁移。
- staging 永远落 **durable 桶**；final 按 kind 路由（material 类→materials 桶=**跨桶**）。
- `complete` 必须 **`prepared→uploading→completed` 两跳**（无 `prepared→completed`）。
- `S3ObjectStore.copy()` **不得调 `_validate_read_ref(src)`**（src 仅作 CopySource，IAM 同账号保读）。
- 完整性：客户端 `crypto.subtle` sha256 + `complete` 下载后复算并 patch + HEAD 校验大小/类型。
- Content-Type 允许集（按 UploadKind）集中一处常量；`complete` HEAD 校验 `== upload.content_type`。
- Contract-first：改契约后 `uv run --extra dev python scripts/export_openapi.py && (cd apps/web && npm run generate:api)`；`schema.d.ts` 禁手改。
- 改 `packages/core/contracts/*` 须同步 `contracts/__init__.py` import+`__all__`。
- ruff line-length 100。**清理 AI slop**：不加多余抽象/防御/复述性注释，匹配周边代码风格。
- 零新依赖（boto3 既有即可）。
- DropZone 调用方 maxSize 不得 >100（前端可更严不可更松）。

## 文件结构（创建/修改）

- `packages/core/storage/object_store.py` — 加 `supports_presign`/`signed_put_url`/`head`/`copy`/`ensure_cors`（base+Local+S3）。
- `packages/core/storage/tiered_object_store.py` — 路由上述新方法到子存储。
- `packages/core/contracts/media.py` + `contracts/__init__.py` — `PrepareUploadResponse`、删 `multipart`、`size_bytes le=`、`ALLOWED_UPLOAD_CONTENT_TYPES`。
- `apps/api/services/uploads.py` — 重写 `prepare_upload`/`complete_upload`/`cancel_upload`；删 `upload_file`/`_stream_upload_to_disk`。
- `apps/api/routers/uploads.py` — prepare `response_model`、删 PUT `/file` 路由。
- `packages/core/config/settings.py` — `max_size_bytes`(两处)→100MiB、加 `presign_ttl_seconds`/`cors_allowed_origins`、删 `chunk_bytes`。
- `apps/web/src/api/client.ts` + `src/hooks/useUpload.ts` + 新 `src/hooks/uploadQueue`(队列) — 直传 util + 并发队列 + sha256。
- `apps/web/src/components/publish/SourceStep.tsx`、`components/library/LibraryAssetUploadModal.tsx`、`components/library/TemplateUploadModal.tsx`、`pages/publish/PublishCenterPage.tsx` — 接队列 + DropZone maxSize=100。
- `scripts/provision_oss_cors.py`(新) — 幂等下发 durable 桶 CORS + `incoming/` 生命周期。
- 测试迁移：10 文件 + 2 契约矩阵（见 Task 7）。

---

### Task 1: object_store 预签名 / head / copy / CORS / supports_presign

**Files:**
- Modify: `packages/core/storage/object_store.py`
- Modify: `packages/core/storage/tiered_object_store.py`
- Test: `tests/api/test_object_store_presign.py`(create)

**Interfaces — Produces:**
- `ObjectStore.supports_presign() -> bool`（base 默认 False）
- `ObjectStore.signed_put_url(uri: str, *, content_type: str, expires_in: timedelta) -> SignedUrlResponse`
- `ObjectStore.head(uri: str) -> ObjectHead`（`@dataclass ObjectHead{size:int; etag:str; content_type:str|None}`，定义在 object_store.py）
- `ObjectStore.copy(src_uri: str, dst_uri: str) -> None`
- `ObjectStore.ensure_cors(origins: list[str], *, expose: list[str] = ["ETag","x-oss-request-id"], max_age: int = 600) -> None`
- 既有 `prepare_upload(filename, purpose, *, content_key: str|None=None, tier=...)` 已支持 `content_key`（object_store.py:104/210），复用之，**不新增 ref_for**。

- [ ] **Step 1: 读现状定锚点** — 读 `object_store.py` 的 `class ObjectStore`(:53起)、`S3ObjectStore`(:156起，含 `__init__`/`_client`/`_validate_read_ref`:326/`_validate_write_ref`:322/`signed_url`:285/`exists`:275)、`parse_object_uri`、`SignedUrlResponse`(contracts/base.py)。确认 `S3ObjectStore` 的 `self._client`、`self.bucket`、`self._read_buckets` 字段名。

- [ ] **Step 2: 写失败测试**（用既有 fake-client 模式，参考 `tests/api/test_object_store_backends.py` 的 fake）

```python
# tests/api/test_object_store_presign.py
import pytest
from datetime import timedelta
from packages.core.storage.object_store import S3ObjectStore, LocalObjectStore, ObjectHead

class FakeS3:
    def __init__(self): self.calls = []
    def head_bucket(self, **k): pass
    def generate_presigned_url(self, op, Params, ExpiresIn):
        self.calls.append(("presign", op, Params, ExpiresIn)); return f"https://host/{Params['Key']}?sig=1"
    def head_object(self, Bucket, Key):
        return {"ContentLength": 123, "ETag": '"abc"', "ContentType": "video/mp4"}
    def copy_object(self, Bucket, Key, CopySource, MetadataDirective):
        self.calls.append(("copy", Bucket, Key, CopySource, MetadataDirective))
    def put_bucket_cors(self, Bucket, CORSConfiguration):
        self.calls.append(("cors", Bucket, CORSConfiguration))

def _store(bucket="cutagent-dev", read=()):
    fake = FakeS3()
    return S3ObjectStore(endpoint_url="https://e", bucket=bucket, read_buckets=read,
        access_key="k", secret_key="s", region_name="r", addressing_style="virtual",
        client_factory=lambda *a, **k: fake), fake

def test_supports_presign():
    s3, _ = _store(); assert s3.supports_presign() is True
    assert LocalObjectStore.__dict__  # local
def test_signed_put_url_signs_put_object_with_content_type():
    s3, fake = _store()
    r = s3.signed_put_url("s3://cutagent-dev/incoming/uploads/u1/v.mp4", content_type="video/mp4", expires_in=timedelta(minutes=15))
    op = fake.calls[0]; assert op[1] == "put_object"
    assert op[2]["Bucket"] == "cutagent-dev" and op[2]["ContentType"] == "video/mp4"
    assert r.url.endswith("sig=1")
def test_head_returns_metadata():
    s3, _ = _store(read=("cutagent-dev",))
    h = s3.head("s3://cutagent-dev/k"); assert isinstance(h, ObjectHead)
    assert h.size == 123 and h.content_type == "video/mp4"
def test_copy_cross_bucket_does_not_read_validate_src():
    # materials store can only "read" itself; copy from dev must NOT be blocked
    s3, fake = _store(bucket="cutagent-materials", read=())  # read set = {materials}
    s3.copy("s3://cutagent-dev/incoming/uploads/u1/v.mp4", "s3://cutagent-materials/portrait/u1/v.mp4")
    c = [x for x in fake.calls if x[0] == "copy"][0]
    assert c[1] == "cutagent-materials" and c[3] == {"Bucket": "cutagent-dev", "Key": "incoming/uploads/u1/v.mp4"}
    assert c[4] == "COPY"
def test_copy_rejects_dst_not_self_bucket():
    s3, _ = _store(bucket="cutagent-dev")
    with pytest.raises(ValueError):
        s3.copy("s3://cutagent-dev/a", "s3://cutagent-other/b")
```

- [ ] **Step 3: 跑测试确认失败** — `…/.venv/bin/python -m pytest tests/api/test_object_store_presign.py -v`（用主 checkout venv + PYTHONPATH=worktree；见执行注记）。Expected: ImportError/AttributeError。

- [ ] **Step 4: 实现 base（默认）**

```python
# object_store.py 顶部加
from dataclasses import dataclass
@dataclass(frozen=True)
class ObjectHead:
    size: int
    etag: str
    content_type: str | None

# class ObjectStore (abstract) 内加默认
def supports_presign(self) -> bool:
    return False
def signed_put_url(self, uri: str, *, content_type: str, expires_in: timedelta) -> SignedUrlResponse:
    raise NotImplementedError("presigned PUT not supported by this backend")
def head(self, uri: str) -> ObjectHead:
    raise NotImplementedError
def copy(self, src_uri: str, dst_uri: str) -> None:
    raise NotImplementedError
def ensure_cors(self, origins: list[str], *, expose: list[str] | None = None, max_age: int = 600) -> None:
    raise NotImplementedError
```
`LocalObjectStore` 不覆盖 `supports_presign`（继承 False）；其余预签名方法保持 base 的 raise（测试/本地不走直传）。

- [ ] **Step 5: 实现 S3ObjectStore**

```python
def supports_presign(self) -> bool:
    return True

def signed_put_url(self, uri, *, content_type, expires_in):
    ref = parse_object_uri(uri)
    self._validate_write_ref(ref)   # 只能签自己写桶的 key
    url = self._client.generate_presigned_url(
        "put_object",
        Params={"Bucket": ref.bucket, "Key": ref.key, "ContentType": content_type},
        ExpiresIn=int(expires_in.total_seconds()),
    )
    return SignedUrlResponse(url=url, expires_at=utcnow() + expires_in, request_id="req_put")

def head(self, uri):
    ref = parse_object_uri(uri)
    self._validate_read_ref(ref)
    resp = self._client.head_object(Bucket=ref.bucket, Key=ref.key)
    return ObjectHead(size=resp["ContentLength"], etag=resp.get("ETag", ""),
                      content_type=resp.get("ContentType"))

def copy(self, src_uri, dst_uri):
    src = parse_object_uri(src_uri)
    dst = parse_object_uri(dst_uri)
    self._validate_write_ref(dst)
    # NOTE: 故意不调 _validate_read_ref(src) —— src 仅作 CopySource，跨桶读由 IAM 保障。
    self._client.copy_object(
        Bucket=dst.bucket, Key=dst.key,
        CopySource={"Bucket": src.bucket, "Key": src.key},
        MetadataDirective="COPY",
    )

def ensure_cors(self, origins, *, expose=None, max_age=600):
    self._client.put_bucket_cors(
        Bucket=self.bucket,
        CORSConfiguration={"CORSRules": [{
            "AllowedOrigins": list(origins),
            "AllowedMethods": ["PUT", "GET", "HEAD"],
            "AllowedHeaders": ["*"],
            "ExposeHeaders": expose or ["ETag", "x-oss-request-id"],
            "MaxAgeSeconds": max_age,
        }]},
    )
```

- [ ] **Step 6: 实现 TieredObjectStore 路由**（`tiered_object_store.py`，参考既有 `_store_for_ref`:111 / `signed_url`:89）

```python
def supports_presign(self) -> bool:
    return self._durable.supports_presign()
def signed_put_url(self, uri, *, content_type, expires_in):
    return self._store_for_ref(parse_object_uri(uri)).signed_put_url(uri, content_type=content_type, expires_in=expires_in)
def head(self, uri):
    return self._store_for_ref(parse_object_uri(uri)).head(uri)
def copy(self, src_uri, dst_uri):
    # 路由到 dst 子存储执行（dst 子存储才有写权限）
    self._store_for_ref(parse_object_uri(dst_uri)).copy(src_uri, dst_uri)
def ensure_cors(self, origins, *, expose=None, max_age=600):
    self._durable.ensure_cors(origins, expose=expose, max_age=max_age)
```
确认 `_store_for_ref`/`_durable` 字段名与现状一致；`parse_object_uri` 已 import。

- [ ] **Step 7: 跑测试通过** — `pytest tests/api/test_object_store_presign.py -v` → PASS。

- [ ] **Step 8: Commit** — `git add packages/core/storage/object_store.py packages/core/storage/tiered_object_store.py tests/api/test_object_store_presign.py && git commit -m "feat(storage): presigned PUT + head + cross-bucket copy + CORS + supports_presign"`

---

### Task 2: 配置上限 + 新配置项

**Files:** Modify `packages/core/config/settings.py`（:344 默认 + :671 builder + 新增字段）

- [ ] **Step 1: 改 `max_size_bytes` 两处 → 100MiB** — `:344` `max_size_bytes: int = 100 * 1024 * 1024`；`:671` `_env_int("CUTAGENT_UPLOAD_MAX_SIZE_BYTES", 100 * 1024 * 1024)`。
- [ ] **Step 2: 在 `UploadSettings` 加字段**：`presign_ttl_seconds: int = 900`、`cors_allowed_origins: tuple[str, ...] = ()`；删 `chunk_bytes`（Task 6 删完 `upload_file` 后无消费者；若此刻仍被引用，留到 Task 6 删）。
- [ ] **Step 3: builder 读 env**：`presign_ttl_seconds=_env_int("CUTAGENT_UPLOAD_PRESIGN_TTL_SECONDS", 900)`；`cors_allowed_origins=tuple(o.strip() for o in _env_str("CUTAGENT_UPLOAD_CORS_ALLOWED_ORIGINS","https://app.shuying.cyou,http://localhost:5173").split(",") if o.strip())`。
- [ ] **Step 4: 测试** — `tests/contract/test_database_seed.py` 或新 `tests/core/test_upload_settings.py`：断言 `build_settings().upload.max_size_bytes == 100*1024*1024` 且 `presign_ttl_seconds == 900`。跑 PASS。
- [ ] **Step 5: Commit** — `… -m "feat(config): 100MiB upload cap + presign TTL + CORS origins"`

---

### Task 3: 契约 — PrepareUploadResponse / 删 multipart / size le= / MIME 允许集

**Files:** Modify `packages/core/contracts/media.py`、`packages/core/contracts/__init__.py`；regen `apps/web/src/api/{openapi.json,schema.d.ts}`。Test `tests/contract/test_upload_contracts.py`(create)。

**Interfaces — Produces:**
- `PrepareUploadResponse{upload_session: UploadSession; put_url: str; put_content_type: str; expires_at: datetime}`
- `ALLOWED_UPLOAD_CONTENT_TYPES: dict[UploadKind, frozenset[str]]`（media.py 模块级常量）

- [ ] **Step 1: 写失败测试**

```python
# tests/contract/test_upload_contracts.py
import pytest
from pydantic import ValidationError
from packages.core.contracts import PrepareUploadRequest, PrepareUploadResponse
from packages.core.contracts.media import ALLOWED_UPLOAD_CONTENT_TYPES, UploadKind

def test_size_cap_enforced():
    with pytest.raises(ValidationError):
        PrepareUploadRequest(kind=UploadKind.publish_video, filename="v.mp4",
                             content_type="video/mp4", size_bytes=100*1024*1024 + 1)
def test_multipart_field_removed():
    assert "multipart" not in PrepareUploadRequest.model_fields
def test_allowlist_has_all_kinds():
    assert set(ALLOWED_UPLOAD_CONTENT_TYPES) == set(UploadKind)
    assert "video/mp4" in ALLOWED_UPLOAD_CONTENT_TYPES[UploadKind.publish_video]
def test_prepare_response_shape():
    f = set(PrepareUploadResponse.model_fields)
    assert {"upload_session","put_url","put_content_type","expires_at"} <= f
```

- [ ] **Step 2: 跑确认失败。**

- [ ] **Step 3: 改 media.py**

```python
# PrepareUploadRequest: 删 `multipart: bool = False`；size_bytes 改：
    size_bytes: int = Field(gt=0, le=100 * 1024 * 1024)

# 新增（放在 CompleteUploadResponse 之后即可）：
class PrepareUploadResponse(ContractModel):
    upload_session: "UploadSession"
    put_url: str
    put_content_type: str
    expires_at: datetime

_VIDEO = frozenset({"video/mp4", "video/quicktime", "video/webm"})
_IMAGE = frozenset({"image/png", "image/jpeg", "image/webp"})
_AUDIO = frozenset({"audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/aac"})
_FONT = frozenset({"font/ttf", "font/otf", "font/woff", "font/woff2",
                   "application/x-font-ttf", "application/vnd.ms-opentype"})
ALLOWED_UPLOAD_CONTENT_TYPES: dict[UploadKind, frozenset[str]] = {
    UploadKind.publish_video: _VIDEO, UploadKind.portrait: _VIDEO,
    UploadKind.broll: _VIDEO, UploadKind.video: _VIDEO,
    UploadKind.image: _IMAGE, UploadKind.cover_template: _IMAGE,
    UploadKind.voice_reference: _AUDIO, UploadKind.bgm: _AUDIO,
    UploadKind.font: _FONT,
}
```

- [ ] **Step 4: 导出** — `contracts/__init__.py` 加 `PrepareUploadResponse` 到 import + `__all__`（`ALLOWED_UPLOAD_CONTENT_TYPES` 不入 `__all__`，按需 `from packages.core.contracts.media import ALLOWED_UPLOAD_CONTENT_TYPES`）。
- [ ] **Step 5: 跑契约测试 PASS。**
- [ ] **Step 6: 重生成契约**（**先做 Task 4/5 router 改动后再 regen 更稳**——见执行注记；此处先跑 `pytest tests/contract/test_upload_contracts.py`）。

---

### Task 4: API `prepare` — 双键 + 签 staging + PrepareUploadResponse + 校验

**Files:** Modify `apps/api/services/uploads.py`(`prepare_upload`)、`apps/api/routers/uploads.py`(prepare `response_model`). Test `tests/api/test_upload_prepare.py`(create) + 既有 `test_upload_object_store.py`（Task 7 迁移）。

- [ ] **Step 1: 写失败测试**（FastAPI TestClient + 内存后端；参考既有上传测试装配）

```python
def test_prepare_returns_presigned_put_and_staging_uri(client):
    r = client.post("/api/uploads/prepare", json={
        "kind": "publish_video", "filename": "v.mp4",
        "content_type": "video/mp4", "size_bytes": 1024})
    assert r.status_code == 201
    body = r.json()
    assert body["put_url"].startswith("http")
    assert body["put_content_type"] == "video/mp4"
    assert body["upload_session"]["object_uri"].startswith(("s3://", "local://"))
    assert "/incoming/uploads/" in body["upload_session"]["object_uri"]
def test_prepare_rejects_bad_content_type(client):
    r = client.post("/api/uploads/prepare", json={
        "kind": "publish_video", "filename": "v.txt",
        "content_type": "text/plain", "size_bytes": 10})
    assert r.status_code == 400 and r.json()["error"]["code"] == "upload.unsupported_type"
```
（内存后端 `LocalObjectStore.supports_presign()` 为 False → prepare 报错；故 prepare 测试需 S3-fake 后端装配，或对内存后端断言"显式报错"。装配细节见执行：用 `client_factory` 注入 FakeS3 的 S3 后端 app，参考 `tests/api/test_object_store_tiered_s3.py`。)

- [ ] **Step 2: 跑确认失败。**

- [ ] **Step 3: 实现 prepare_upload**

```python
import uuid as _uuid
from datetime import timedelta
from packages.core.contracts.media import ALLOWED_UPLOAD_CONTENT_TYPES

_STAGING_PURPOSE = "incoming/uploads"

def prepare_upload(payload: c.PrepareUploadRequest, request: Request) -> c.PrepareUploadResponse:
    store = object_store(request)
    if not store.supports_presign():
        raise NodeExecutionError(c.ErrorCode.upload_invalid_state,
            "Object store backend does not support presigned uploads.")
    allowed = ALLOWED_UPLOAD_CONTENT_TYPES.get(payload.kind, frozenset())
    if payload.content_type not in allowed:
        raise NodeExecutionError(c.ErrorCode.upload_unsupported_type,
            f"Content type {payload.content_type} not allowed for {payload.kind.value}.")
    key_uuid = _uuid.uuid4().hex
    staging_ref = store.prepare_upload(payload.filename, _STAGING_PURPOSE, content_key=key_uuid)
    ttl = timedelta(seconds=settings(request).upload.presign_ttl_seconds)
    signed = store.signed_put_url(staging_ref.uri, content_type=payload.content_type, expires_in=ttl)
    upload = c.UploadSession(
        id=new_id("upl"), kind=payload.kind, case_id=payload.case_id,
        filename=payload.filename, content_type=payload.content_type,
        size_bytes=payload.size_bytes, sha256=payload.sha256,
        object_uri=staging_ref.uri, stabilize=payload.stabilize,
    )
    if upload_repository(request) is not None:
        upload = upload_repository(request).create_upload(upload)
    else:
        repository(request).uploads[upload.id] = upload
    return c.PrepareUploadResponse(
        upload_session=upload, put_url=signed.url,
        put_content_type=payload.content_type, expires_at=signed.expires_at)
```
（注意：`upload_url` 字段不再用于签名 URL；`PrepareUploadResponse.put_url` 才是。）

- [ ] **Step 4: router** — `apps/api/routers/uploads.py` prepare：`response_model=c.PrepareUploadResponse`，函数体不变。
- [ ] **Step 5: 跑 PASS。**
- [ ] **Step 6: Commit** — `… -m "feat(api): presigned-PUT prepare returns PrepareUploadResponse + MIME/size guards"`

---

### Task 5: API `complete` — 两跳 + HEAD + 复算 sha256 + staging→final + 删 staging

**Files:** Modify `apps/api/services/uploads.py`(`complete_upload`、`_normalize_upload_video`/`_stabilize_upload_video` 末尾不需删 staging——staging 删在 complete 统一做). Test `tests/api/test_upload_complete.py`(create)。

- [ ] **Step 1: 写失败测试**（S3-fake 后端：prepare→fake 标记 staging 存在→complete）。断言：①complete 后 `upload_session.object_uri` 指向 `{kind}/...` final（非 `incoming/uploads/`）；②fake 记录了一次 `copy_object`(dev→…) 与一次 `delete_object`(staging)；③HEAD size 不符→400 `upload.size_mismatch`；④sha256 复算后 artifact.sha256 非空。

- [ ] **Step 2: 跑确认失败。**

- [ ] **Step 3: 实现 complete_upload**（替换现 :133-）。要点顺序：

```python
def complete_upload(payload, request) -> c.CompleteUploadResponse:
    store = object_store(request)
    upload = _get_upload_or_raise(payload.upload_session_id, request)  # 抽小helper或内联
    staging_uri = upload.object_uri
    # 两跳：先到 uploading
    upload = _patch_status(request, upload.id, c.UploadStatus.uploading)
    # HEAD 校验（存在/大小/类型）
    head = store.head(staging_uri)
    declared = payload.size_bytes or upload.size_bytes
    if declared is not None and head.size != declared:
        store.delete(staging_uri); _patch_status(request, upload.id, c.UploadStatus.failed)
        raise NodeExecutionError(c.ErrorCode.upload_size_mismatch, "Upload size mismatch.")
    if head.content_type and head.content_type != upload.content_type:
        store.delete(staging_uri); _patch_status(request, upload.id, c.UploadStatus.failed)
        raise NodeExecutionError(c.ErrorCode.upload_unsupported_type, "Content type mismatch.")
    # 下载+probe（沿用 _probe_upload_media → local_object_path）
    media_info = _probe_upload_media(request, upload)
    # 复算 sha256（local_object_path 已下载缓存；用 sha256_file）
    local = local_object_path(store, staging_uri)
    actual_sha = sha256_file(local)
    if payload.sha256 and payload.sha256 != actual_sha:
        store.delete(staging_uri); _patch_status(request, upload.id, c.UploadStatus.failed)
        raise NodeExecutionError(c.ErrorCode.upload_sha256_mismatch, "Upload sha256 mismatch.")
    upload = _patch_upload_fields(request, upload.id, {"sha256": actual_sha})
    # 可选 normalize/stabilize（沿用现逻辑；会把 object_uri 改写到 media-normalized/...）
    is_av_video = media_info and media_info.media_type == "video" and upload.kind in {c.UploadKind.portrait, c.UploadKind.broll, c.UploadKind.video}
    if is_av_video and settings(request).upload.normalize_video:
        upload, media_info = _normalize_upload_video(request, upload)
    if upload.stabilize and upload.kind in {c.UploadKind.portrait, c.UploadKind.broll, c.UploadKind.video}:
        upload, media_info = _stabilize_upload_video(request, upload)
    # 定 final：若 normalize/stabilize 改写过(object_uri 已变)，final 即其输出；否则 copy staging→final
    if upload.object_uri == staging_uri:
        final_uri = _derive_final_uri(store, staging_uri, upload.kind)  # ref_for: prepare_upload(filename, kind.value, content_key=uuid)
        store.copy(staging_uri, final_uri)
        upload = _patch_upload_fields(request, upload.id, {"object_uri": final_uri})
    # 无条件删 staging（两条路径都删）
    if upload.object_uri != staging_uri:
        store.delete(staging_uri)
    # 第二跳：completed + 建 artifact/asset/package（沿用现 :158- 逻辑，artifact sha256=upload.sha256）
    upload = _patch_status(request, upload.id, c.UploadStatus.completed)
    ...（artifact + media_asset/publish_package + thumbnails，照现状）
```
`_derive_final_uri(store, staging_uri, kind)`：解析 staging key 取 `{uuid}/{filename}`，`store.prepare_upload(filename, kind.value, content_key=uuid).uri`。**复用 `prepare_upload(content_key=)`，不新增方法。**

- [ ] **Step 4: 跑 PASS。**
- [ ] **Step 5: Commit** — `… -m "feat(api): complete verifies via HEAD+sha256, copies staging→final, two-hop status"`

---

### Task 6: 删 proxy + cancel 删 staging

**Files:** Modify `apps/api/routers/uploads.py`(删 PUT `/file`)、`apps/api/services/uploads.py`(删 `upload_file`+`_stream_upload_to_disk`、改 `cancel_upload`)、`settings.py`(删 `chunk_bytes`)。

- [ ] **Step 1: 删 PUT `/file` 路由**（routers :18-23）与 `upload_file`/`_stream_upload_to_disk`（services :33-64, :86-130）。删 `chunk_bytes`（settings :346）及其引用。
- [ ] **Step 2: cancel_upload 删 staging**

```python
def cancel_upload(upload_session_id, request) -> c.UploadSession:
    store = object_store(request); upload = _get_upload_or_raise(upload_session_id, request)
    if upload.object_uri and upload.status in {c.UploadStatus.prepared, c.UploadStatus.uploading}:
        try:
            if store.exists(parse_object_uri(upload.object_uri)):
                store.delete(upload.object_uri)
        except Exception:  # noqa: BLE001 — best-effort 清理，不阻断取消
            pass
    return _patch_status(request, upload_session_id, c.UploadStatus.cancelled)
```
- [ ] **Step 3: 跑 `pytest tests/api/test_uploads*.py -v`**（此刻旧 proxy 测试会红→Task 7 修）。
- [ ] **Step 4: Commit**（与 Task 7 合并提交，保 CI 绿）。

---

### Task 7: 迁移命中 proxy 的测试（10 文件 + 2 契约矩阵）

**Files（spec §8 全清单）:** `tests/api/test_upload_object_store.py`(655 行/11 处，含 `:304` size-mismatch 测试**重设计**：content_type 改 `video/mp4` + fake HEAD 返回不匹配 Content-Length 断言 `upload.size_mismatch`)、`test_media_replacement.py`、`test_annotation_batch.py`、`test_publish_copy_cover_endpoints.py`、`test_upload_streaming_normalize.py`、`tests/integration/test_sqlalchemy_{auth_uploads,media_assets,publishing,voices}.py`、`tests/golden/test_case_publishing_ops.py`；契约矩阵 `tests/contract/test_api_contract_matrix.py`(:26 删 `/file` 行)、`tests/contract/test_openapi_matrix.py`(:16 删条目)。

- [ ] **Step 1: 建测试 helper** `tests/api/_upload_helpers.py`：`def upload_via_direct(client, *, kind, filename, content_type, body) -> dict`（prepare → 用 fake/moto 把 body 落到 staging → complete，返回 CompleteUploadResponse）。所有调用方改用它替代「prepare + PUT /file + complete」。
- [ ] **Step 2: 逐文件替换** `client.put("/api/uploads/{id}/file", files=...)` → `upload_via_direct(...)`。`test_upload_streaming_normalize` 与 `test_upload_object_store` 的"服务端流式"用例改为「complete 下载后处理 / HEAD 校验」语义。
- [ ] **Step 3: 契约矩阵删 `/file` 条目。**
- [ ] **Step 4: 跑 `pytest tests/api tests/integration tests/contract tests/golden -q`** → 全绿。
- [ ] **Step 5: Commit**（含 Task 6）— `… -m "refactor(api): delete proxy /file endpoint; migrate uploads to direct-PUT; cancel cleans staging"`

---

### Task 8: 重生成契约 + 前端直传

**Files:** regen `apps/web/src/api/{openapi.json,schema.d.ts}`；Modify `apps/web/src/api/client.ts`、`src/hooks/useUpload.ts`、新 `src/hooks/useUploadQueue.ts`、`components/publish/SourceStep.tsx`、`pages/publish/PublishCenterPage.tsx`、`components/library/{LibraryAssetUploadModal,TemplateUploadModal}.tsx`。

- [ ] **Step 1: 重生成契约** — `uv run --extra dev python scripts/export_openapi.py && (cd apps/web && npm install && npm run generate:api)`；`git diff --stat apps/web/src/api/`。
- [ ] **Step 2: client.ts 直传 util**（替换 `uploadFormData`/`uploadFile`）

```ts
export async function sha256Hex(file: File): Promise<string> {
  const buf = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
// 裸 body PUT 到预签名 URL，带进度；不带 cookie/FormData
export function putToOss(url: string, file: File, contentType: string,
    onProgress?: (p: {loaded:number;total:number;percent:number}) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", contentType);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(
      {loaded:e.loaded,total:e.total,percent:Math.round(e.loaded/e.total*100)});
    xhr.onload = () => (xhr.status>=200&&xhr.status<300)?resolve():reject(new Error(`OSS ${xhr.status}`));
    xhr.onerror = () => reject(new Error("network")); xhr.onabort = () => reject(new Error("aborted"));
    xhr.send(file);
  });
}
// api.uploads: prepare(返回 PrepareUploadResponse) / complete / cancel（删 uploadFile）
```
- [ ] **Step 3: useUpload.ts 三步直传** — prepare → `putToOss(put_url, file, put_content_type, onProgress)`（失败整文件重试，默认 2 次指数退避；URL 过期重新 prepare）→ complete(`{upload_session_id, sha256: await sha256Hex(file), size_bytes: file.size, metadata}`)。复用主 checkout WIP 的 `fileName/loadedBytes/totalBytes/onProgress` 进度形态。
- [ ] **Step 4: useUploadQueue.ts** — 多文件并发（上限如 3），每文件 `useUpload` 状态/重试，替换 `SourceStep` 的串行 for-await。
- [ ] **Step 5: DropZone maxSize** — `SourceStep.tsx:149` 600→100；`LibraryAssetUploadModal.tsx:64` 非字体 120→100（字体 40 留）；`TemplateUploadModal.tsx:137` 500→100。`VoiceModals`(80) 不动。
- [ ] **Step 6: 构建校验** — `(cd apps/web && npm run build)` 通过（TS 无错）。
- [ ] **Step 7: Commit** — `… -m "feat(web): browser-direct OSS upload (presigned PUT + queue + crypto.subtle sha256); drop proxy path"`

---

### Task 9: CORS 下发脚本 + 生命周期 + 文档 + 真 OSS 集成验证

**Files:** Create `scripts/provision_oss_cors.py`；Modify `.env.example`(加 `CUTAGENT_UPLOAD_PRESIGN_TTL_SECONDS`/`CUTAGENT_UPLOAD_CORS_ALLOWED_ORIGINS`)；docs（`apps/api` 或 `packages/core/storage` 的 CLAUDE.md 提一句）；`tests/integration/test_oss_direct_upload_real.py`(gated)。

- [ ] **Step 1: provision 脚本** — 读 `build_object_store_settings()`，对 durable 写桶（`bucket` + 必要时 prod）调 `ensure_cors(origins=settings.upload.cors_allowed_origins)`；对 `incoming/uploads/` 前缀下发 OSS 生命周期（`put_bucket_lifecycle_configuration`，Expiration Days=1，Prefix=`incoming/uploads/`）。幂等、可重复跑。
- [ ] **Step 2: gated 集成测试** — 复刻本会话冒烟（预签名 PUT→HEAD→同桶+跨桶 copy→delete + get_bucket_cors），`@pytest.mark.skipif(无真凭据)`。
- [ ] **Step 3: `.env.example` + CLAUDE.md 文档化新 env + CORS 必须先下发。**
- [ ] **Step 4: Commit** — `… -m "feat(ops): OSS CORS+lifecycle provisioning script + gated direct-upload integration test"`

---

### Task 10: CI 门禁 + 清 AI slop + PR

- [ ] **Step 1: 全量门禁** — `bash scripts/ci_gate.sh`（需 PG 55432 + Temporal 7233 + MinIO；见执行注记的本机配方）。逐项绿：unit / contract（含 openapi 漂移）/ frontend（build+tsc）/ integration。
- [ ] **Step 2: 清 slop（自审 + 子代理对抗审，子代理用绝对路径读工作树）** — 删多余抽象/防御 try-except/复述性注释；确认无新依赖；`prepare_upload(content_key=)` 复用而非新方法；`copy()` 无 `_validate_read_ref(src)`；helper 不过度拆分。`ruff check`（line-length 100）。
- [ ] **Step 3: rebase 到最新 origin/main 重验**（长会话 origin/main 可能前移；见记忆 workflow-agent-cwd-and-stale-base）。
- [ ] **Step 4: 开 PR** — `gh pr create`，正文含 spec/plan 链接、改动摘要、真 OSS 冒烟结论、测试迁移说明。main 受保护：作者本人 `--admin` 在 CI 绿 + rebase 后合（见记忆 cutagent-ci-automerge-not-required）。

---

## 执行注记（本机/worktree）

- **解释器/路径**：worktree 无 `.venv`；用主 checkout `…/cutagent-genesis/.venv/bin/python`，`PYTHONPATH` 指向 worktree 根；node_modules 软链或在 worktree `npm install`。见记忆 cutagent-worktree-verify-recipe。
- **真 OSS 冒烟**：`.env.local` 已 armed 真凭据；脚本读 `build_object_store_settings()`，沙箱外网络跑，`_smoke/`/`incoming/` 前缀写完即删。
- **CI 真门禁** = `scripts/ci_gate.sh`（无 ruff 独立项但有 lint；需起 PG/Temporal/MinIO）。
- **本地 secret 污染**：`.data/secrets` 真密钥会污染 memory 后端假失败；复刻 CI 用 `CUTAGENT_SECRET_STORE_DIR=<空目录>`。见记忆 cutagent-local-test-secrets-pollution。

## Self-Review（spec 覆盖核对）

- §3 决策 1-7 → Task 1/3/4/5/6/8 全覆盖（预签名URL/单PUT≤100MiB/完整性/后处理留API/删proxy/staging→final/工作树）。
- §4.1 数据流 → Task 4(prepare)+5(complete)。§4.2 三道闸 → Task 2(le=)+3(prepare校验)+5(HEAD)+8(DropZone)。§4.5 MIME → Task 3。
- §5.1 对象存储新方法+Tiered路由+copy不validate_read_ref → Task 1。§5.2 契约 → Task 3。§5.3 API → Task 4/5/6。§5.4 无迁移 → 全程不建 alembic。§5.5 前端+三个 DropZone → Task 8。§5.6 CORS仅durable+生命周期 → Task 9。§5.7 配置两处+新字段 → Task 2。
- §8 测试迁移 10+2（含 test_upload_object_store 655行重设计）→ Task 7。§9 落地顺序 → Task 1→2→3→4→5+6→7→8→9→10。§10 风险 → 执行注记 + Task 10 rebase/deslop。
- 无占位符；类型一致（`PrepareUploadResponse`/`ObjectHead`/`ALLOWED_UPLOAD_CONTENT_TYPES`/`signed_put_url`/`head`/`copy` 跨任务一致引用）。
