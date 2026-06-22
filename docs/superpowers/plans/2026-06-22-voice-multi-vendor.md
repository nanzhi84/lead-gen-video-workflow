# 素材库音色分厂商 + 火山豆包接入 · 实现计划

> **For agentic workers:** 用 superpowers:subagent-driven-development 或 executing-plans 执行。本计划由主代理在工作树 `voice-multi-vendor` 串行执行（子代理仅 verify）。spec 真相源：`docs/superpowers/specs/2026-06-22-voice-multi-vendor-design.md`。

**Goal:** 素材库音色改造为分厂商（MiniMax + 火山豆包）多音色管理 + 分厂商试听，火山接入合成/复刻/同步已复刻音色/自动签发 key。

**Architecture:** `ProviderGateway` 按 `provider_id` 分发（零改）；新增 `VolcengineTTSProvider` 与 MiniMax 并存；`VoiceProfile` 加 `vendor`+`status`；火山数据面用 x-api-key（合成/复刻），管理面用 AK/SK V4 签名（同步音色/签发 key）。

**Tech Stack:** Python FastAPI + Pydantic v2 + SQLAlchemy/Alembic + Temporal(本次不碰)；React/Vite TS；httpx；火山 OpenAPI。

## Global Constraints（每个 task 隐含）

- **Contract-first**：改 API 形状 → `python scripts/export_openapi.py && (cd apps/web && npm run generate:api)` 重生成 `openapi.json`+`schema.d.ts`；`schema.d.ts` 禁手改。
- 领域类型唯一源 `packages/core/contracts`（Pydantic v2）。
- 迁移只在 `packages/core/storage/alembic/versions/`；新建 `0021`，`down_revision="0020_selection_reservation_active_slot"`（实现时读 0020 文件确认 revision id）。
- 外部调用经 `ProviderGateway` 按 capability 分发；secret 只进 SecretStore，profile 存 `secret_ref`。
- 降级/失败显式上报（`ErrorCode`），不静默。
- ruff line-length 100。
- 测试用空 `CUTAGENT_SECRET_STORE_DIR` 复刻 CI（避免本地 `.data/secrets` 污染）。
- 工作树跑测试：`PYTHONPATH` + 主 `.venv`；前端 symlink `node_modules`（见记忆 cutagent-worktree-verify-recipe）。

## 火山接口契约（实测坐实，实现直接用）

- 数据面合成：`POST https://openspeech.bytedance.com/api/v1/tts`，header `x-api-key`，body `{app:{cluster},user:{uid},audio:{voice_type,encoding:"mp3",speed_ratio},request:{reqid,text,operation:"query"}}`；cluster 复刻=`volcano_icl`/预置=`volcano_tts`；voice_type 复刻=SpeakerID(S_…)；返回 `{code:3000,message,data:base64,addition:{duration}}`。
- 管理面（AK/SK V4，host `open.volcengineapi.com`，region `cn-north-1`，Service `speech_saas_prod`，POST JSON，签名复用 `packages/ops/balance/providers/volcengine.py` 扩展 POST）：
  - `ListMegaTTSTrainStatus`（Ver `2025-05-21`，body `{AppID}`）→ `Result.Statuses[]{SpeakerID,Alias,State,InstanceStatus,DemoAudio,ResourceID,AvailableTrainingTimes}`
  - `ListAPIKeys`（Ver `2025-05-20`，body `{AppID}`）→ `Result.APIKeys[]{ID,Name,APIKey(明文),Disable}`
  - `CreateAPIKey`（Ver `2025-05-20`，body `{AppID,Name}`）→ 建后 `ListAPIKeys` 按 Name 捞明文
- 复刻数据面（mega_tts，实测补全）：`POST https://openspeech.bytedance.com/api/v1/mega_tts/audio/upload` + `/api/v1/mega_tts/status`，header `x-api-key`（或 `Authorization: Bearer;<token>`+`Resource-Id: volc.megatts.voiceclone`，实测择一）。

---

## 文件结构

| 文件 | 责任 |
|---|---|
| `packages/core/contracts/media.py` | `VoiceProfile` 加 `vendor`+`status`；删 `DesignVoiceRequest`；`CloneVoiceRequest` 加 `provider_profile_id`(已有) |
| `packages/core/storage/database.py` | `VoiceProfileRow` 加 `vendor`+`status` 列 |
| `packages/core/storage/alembic/versions/0021_voice_vendor_status.py` | 幂等 ALTER（inspect-then-add，参照 0006）|
| `packages/media/sqlalchemy_repository.py` | `voice_row_to_contract`/`upsert_voice`/`clone`/`design(删)` 带 vendor/status |
| `packages/media/voice_provider_bridge.py` | `persist_provider_voice` 带 vendor/status |
| `packages/core/storage/repository.py`,`seed.py` | 内存 `voice_sandbox` 种子补默认值 |
| `packages/ai/providers/volcengine_tts.py` | 新建火山适配器（speech/clone/voice_list + 管理面 V4 签名）|
| `packages/ai/providers/__init__.py` | 注册 `VolcengineTTSProvider` |
| `packages/core/storage/provider_seed.py` | `volcengine.tts.prod` profile + price catalog/item |
| `packages/ai/netpolicy.py` | `DEFAULT_ALLOWED_HOSTS` 加 `openspeech.bytedance.com`,`open.volcengineapi.com` |
| `apps/api/services/voices.py` | vendor 回填/按厂商能力降级/sync 按厂商遍历/状态刷新/删 design |
| `apps/api/routers/voices.py` | 删 design 端点；加 `GET ?vendor=` 过滤；preview 不变 |
| `apps/web/src/pages/library/VoicesTab.tsx` 等 | 厂商一级 Tab；克隆选厂商；卡片厂商+status 徽标；试听分厂商；删 design 入口；training 轮询 |

---

## 阶段 A — 数据模型与契约

### Task 1: VoiceProfile/VoiceProfileRow 加 vendor + status + 迁移 + 契约重生成

**Files:** Modify `media.py:362`、`database.py:338-346`；Create `alembic/versions/0021_voice_vendor_status.py`；Modify `sqlalchemy_repository.py`(voice_row_to_contract)、`repository.py`/`seed.py`(种子)；Test `tests/storage/test_voice_vendor_status_migration.py`。

**Interfaces:** Produces — `VoiceProfile.vendor: str`（默认 `""`→回填）、`VoiceProfile.status: Literal["ready","training","failed"]="ready"`；`VoiceProfileRow.vendor/status` 列。

- [ ] 测试先行：建测试断言 `VoiceProfile(vendor=..., status=...)` 可构造、默认 `status="ready"`；迁移幂等（重复 upgrade 不报错）。
- [ ] `media.py` VoiceProfile 加 `vendor: str = ""`、`status: VoiceStatus = "ready"`（新增 `VoiceStatus = Literal["ready","training","failed"]`）。
- [ ] `database.py` VoiceProfileRow 加 `vendor: Mapped[str] = mapped_column(String, nullable=False, default="")`、`status: Mapped[str] = mapped_column(String, nullable=False, default="ready")`。
- [ ] 写 `0021` 迁移：`down_revision="0020_selection_reservation_active_slot"`，`upgrade()` inspect-then-add 两列（参照 `0006`），历史行 `status='ready'`、`vendor` 回填（`UPDATE voice_profiles SET vendor=split_part(provider_profile_id,'.',1)` 反推不到留 `''`）；`downgrade()` drop 两列。
- [ ] `voice_row_to_contract` + `upsert_voice` 带 vendor/status；内存种子 `voice_sandbox` 补 `vendor="sandbox",status="ready"`。
- [ ] 重生成契约：`python scripts/export_openapi.py && (cd apps/web && npm run generate:api)`。
- [ ] 验收：`pytest tests/storage/test_voice_vendor_status_migration.py -q`；`pytest tests/storage tests/integration/test_sqlalchemy_* -q`；契约无漂移。
- [ ] commit。

## 阶段 B — 火山 provider 适配器

### Task 2: 火山管理面客户端（V4 签名 + List/Create）

**Files:** Create `packages/ai/providers/volc_openapi.py`（V4 签名 POST + `list_mega_tts_train_status(appid)` / `list_api_keys(appid)` / `create_api_key(appid,name)`）；Test `tests/providers/test_volc_openapi.py`。

**Interfaces:** Produces — `volc_sign_headers(ak,sk,service,version,action,region,body:bytes)->dict`；`VolcOpenAPI(client, ak, sk).list_voices(appid)->list[dict]`（映射 `[{voice_id=SpeakerID, display_name=Alias, status, preview_url=DemoAudio}]`）、`.ensure_api_key(appid,name)->str`（ListAPIKeys 取明文,无则 Create 再取）。

- [ ] 测试：mock httpx，断言签名头 `Authorization: HMAC-SHA256 Credential=.../speech_saas_prod/request`、`list_voices` 映射 Statuses→统一形状、`ensure_api_key` 先 List 后 Create 回退。
- [ ] 实现 V4 签名（搬 `volcengine.py:_signed_headers` 扩展 POST：method=POST、query=`Action=X&Version=Y`、payload=sha256(body)、补 Content-Type）。
- [ ] 验收：`pytest tests/providers/test_volc_openapi.py -q`。commit。

### Task 3: 火山数据面合成 speech

**Files:** Create `packages/ai/providers/volcengine_tts.py`（先实现 `_speech`）；Test `tests/providers/test_volcengine_tts.py`。

**Interfaces:** Produces — `VolcengineTTSProvider(provider_id="volcengine.tts")`，`invoke_with_context` 按 `operation` 分发；`_speech` 用 x-api-key(require_secret) + cluster(option,默认 volcano_icl) + voice_type → POST openspeech /api/v1/tts → `code==3000` 取 base64 → `store_media_bytes(audio_tts)` → ProviderResult(audio_artifact_id/audio_uri/duration_sec/voice_id, input_tokens=len(text), estimated_cost)。

- [ ] 测试：mock 合成返回 `{code:3000,data:<base64>,addition:{duration}}`，断言解码+产物+cost；`code!=3000` → `provider_remote_failed`。
- [ ] 实现 `_speech`（capability 守卫 tts.speech；netpolicy host）。
- [ ] 验收：`pytest tests/providers/test_volcengine_tts.py -k speech -q`。commit。

### Task 4: 火山复刻 clone（mega_tts 数据面，先实测补全）

**Files:** Modify `volcengine_tts.py`(`_clone`)；Test 同上。

**Interfaces:** Produces — `_clone`：取 reference 音频（同 minimax `reference_upload_session_id`/`reference_audio_uri`）→ POST mega_tts/audio/upload(speaker_id+base64 audio) → 返回 status=`training` + SpeakerID（不内联轮询）；状态由 service 层轮询 `list_mega_tts_train_status`。

- [ ] **实测先行**：用 `$CLAUDE_JOB_DIR/tmp/volc_call`-类脚本 + x-api-key 实测 mega_tts/audio/upload+status 的精确 body/鉴权/返回，记录到 spec 附录。
- [ ] 测试：mock 上传返回 training。
- [ ] 实现 `_clone`（产出 SpeakerID + status=training）。
- [ ] 验收：`pytest tests/providers/test_volcengine_tts.py -k clone -q`。commit。

### Task 5: 火山 voice_list + 注册 + seed + netpolicy + price

**Files:** Modify `volcengine_tts.py`(`_voice_list` 调 Task2 VolcOpenAPI)、`providers/__init__.py`(注册)、`provider_seed.py`(profile+price)、`netpolicy.py`(host)；Test `tests/providers/test_netpolicy.py`、`tests/contract/test_provider_*`。

**Interfaces:** Produces — `register_real_provider_plugins` 含 `VolcengineTTSProvider`；seed `volcengine.tts.prod`（capability=tts.speech, default_options={appid,cluster,data_base_url,openapi_service,openapi_versions,region}, secret_ref=`volc_tts_prod.secret`, concurrency_key=`volcengine:tts.speech`）+ `ProviderPriceItem(unit=input_token)`。

- [ ] `_voice_list` 调 VolcOpenAPI.list_voices(appid) 映射统一形状。
- [ ] 注册 + seed（profile 只挂 secret_ref 不挂值）+ netpolicy host + price。
- [ ] 验收：`pytest tests/providers -q`；seed 安全不变量测试通过。commit。

## 阶段 C — 服务层

### Task 6: services/voices.py 分厂商改造 + 状态机

**Files:** Modify `apps/api/services/voices.py`、`apps/api/routers/voices.py`；Test `tests/api/test_voices_*`。

**Interfaces:** Produces — clone 必带 `provider_profile_id`，回填 `vendor`+`status`；`sync_voices` 遍历所有 enabled tts.speech profile 分厂商同步（带 vendor/status/preview_url）；新增 `POST /api/voices/{id}/refresh-status`（火山 training 音色查 `list_mega_tts_train_status` 转 ready/failed）；`GET /api/voices?vendor=` 过滤；厂商不支持 operation → `provider_unsupported_option`。

- [ ] 测试：sync 多厂商遍历回填 vendor；refresh-status training→ready；vendor 过滤；clone 回填 vendor=volcengine/status=training。
- [ ] 实现（`_select_tts_profile_for_sync` 改遍历；vendor 回填取 profile.provider_id 前缀；状态刷新端点）。
- [ ] 重生成契约（新端点+vendor 参数）。验收：`pytest tests/api/test_voices_* -q`。commit。

### Task 7: 删 design 全链路

**Files:** Modify `media.py`(删 DesignVoiceRequest)、`voices.py`(删 design_voice)、`routers/voices.py`(删 /design)、`minimax.py`(删 _design + 分发分支)、`sqlalchemy_repository.py`(删 design_voice)；Test 更新。

**Interfaces:** `source="designed"` 枚举值**保留**（兼容历史）；design 端点/请求/方法全删。

- [ ] 测试：`/api/voices/design` 404；历史 `source=designed` 音色仍可 list/preview。
- [ ] 删除 design 链路（前端入口在 Task 9）。重生成契约。
- [ ] 验收：`pytest tests/api tests/providers -q`。commit。

## 阶段 D — 前端

### Task 8: 厂商一级 Tab

**Files:** Modify `apps/web/src/pages/library/VoicesTab.tsx`、`components/library/libraryModel.ts`、`api/client.ts`(list 加 vendor)、`api/realData.ts`(unknown 兜底)；Test 前端 typecheck。

**Interfaces:** Produces — `VoiceVendorFilter` 类型 + `vendorLabels`/`vendorTone`；Tab「全部/MiniMax/火山豆包」切 `vendorFilter` state → list `?vendor=`。

- [ ] 实现 Tab + state + 查询；vendor 来自后端字段。
- [ ] 验收：`(cd apps/web && npm run build)` 通过；typecheck 无错。commit。

### Task 9: 克隆弹窗选厂商 + 删 design 入口

**Files:** Modify `components/library/VoiceModals.tsx`(CloneVoiceModal 厂商下拉,删 DesignVoiceModal)、`VoicesTab.tsx`(删设计按钮)、`libraryModel.ts`。

**Interfaces:** Produces — CloneVoiceModal 厂商下拉（数据 `api.providers.profiles({capability:"tts.speech"})` 按 provider_id 分组）→ clone payload 带 provider_profile_id。

- [ ] 实现厂商下拉 + 删 design 入口（保留 designed 历史音色展示）。
- [ ] 验收：`npm run build` 通过。commit。

### Task 10: VoiceCard 厂商/status 徽标 + 试听分厂商 + training 轮询

**Files:** Modify `components/library/VoiceCard.tsx`、`VoiceGeneratorPanel.tsx`、`VoicesTab.tsx`。

**Interfaces:** Produces — 卡片厂商徽标 + status 徽标（training 禁用试听+轮询 `refresh-status`）；试听面板音色下拉 optgroup 按厂商分组；training 音色轮询转 ready 解锁。

- [ ] 实现徽标 + optgroup + training 轮询（setInterval 调 refresh-status，ready 停）。
- [ ] 验收：`npm run build` 通过。commit。

## 阶段 E — verify / CI / PR

### Task 11: 子代理多维 verify + 修复

- [ ] Workflow 多 agent verify（**prompt 给工作树绝对路径** `/Users/yoryon/Projects/cutagent-genesis/.claude/worktrees/voice-multi-vendor`，禁读主 checkout）：① 正确性(火山签名/状态机/错误码) ② 契约一致(openapi/schema.d.ts 与后端) ③ 测试覆盖与真假阳性 ④ 前后端 vendor/status 一致 ⑤ design 删除彻底性+历史兼容 ⑥ 安全(secret 不入代码/host 白名单)。
- [ ] 逐条修复确认为真的问题（假阳性记录不改）。

### Task 12: CI gate（本地 + 推送）

- [ ] 本地全量：`scripts/ci_gate.sh`（需 PG 55432 + Temporal 7233 + MinIO；用 throwaway DB）；ruff；前端 build。
- [ ] 推送分支触发 GitHub Actions（unit/integration/frontend）；全绿。

### Task 13: PR

- [ ] `finishing-a-development-branch`：push 分支 → `gh pr create`（标题/正文含方案摘要 + 实测坐实 + 前置依赖：火山 secret arm/余额充值/key 轮换）。

## Self-Review（spec 覆盖核对）

- 数据模型 vendor+status → Task 1 ✓；火山三链路（合成/复刻/同步+签发）→ Task 2-5 ✓；服务层分厂商+状态机 → Task 6 ✓；砍 design → Task 7 ✓；UI 厂商 Tab+分厂商试听+training → Task 8-10 ✓；试听 DemoAudio 优先 → Task 6(sync 带 preview_url)+Task 10 ✓；verify/CI/PR → Task 11-13 ✓。
- 前置依赖（secret arm/余额/key 轮换/host 白名单/price）→ Task 5+13 ✓。
