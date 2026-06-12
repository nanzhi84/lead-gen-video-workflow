# M6O 施工简报：分层存储（过渡产物本地临时·用完即删；成品/provider 输入上 OSS）

负责：Codex（执行）/ Claude（架构 + 验收）
分支：`feat/m6o-tiered-ephemeral-storage`
来源：用户裁决——远端 OSS 出片慢且占盘，要求「过渡文件用完即删除、成品放 OSS」。本批让**中间产物落本地临时存储、run 成功后即删**（不再上传远端 OSS→渲染快；不再永久占盘→省盘），**成品/字幕/封面/TTS 音频仍落 durable（OSS/MinIO）**。

## 已勘定事实（勿推翻）

- store_file 调用点（digital_human.py）：line 235 seed uploaded_file(durable)、line 925 audio_tts(durable，ASR/HeyGem 要用)、**line 1897 video_portrait_track(中间，仅本 run 的 _lipsync/_render 消费)**、**line 2040 video_rendered(中间，仅本 run 的 _subtitle_and_bgm_mix 消费)**、line 2101 video_final(成品)、line 2103 subtitle_ass(成品)、line 2166 cover_image(成品)。
- 真出片证过：strict 真对齐 OSS 全链路成片成功（run_e8399a9fa0a4）；瓶颈是中间大视频单发/多发都要传上海。
- HeyGem 插件 `local_path_for_uri` 会把 URI 落地为本地路径再上传 RunningHub——**中间产物即使在本地临时存储，_lipsync 仍能本地读到**（无需公网/OSS）。
- reuse.py `compute_reuse_plan` 校验旧 run 产物存在；缺失→该节点重跑（非致命，优雅降级）。失败 run 不会到 finalize（中间文件保留供重试）。

## 设计

新增「分层对象存储」：中间产物走**本地临时 store**（用完即删），其余走**durable store**（现有 OSS/MinIO/Local）。

### A. TieredObjectStore（packages/core/storage/object_store.py）

- A1 新增 `class TieredObjectStore(ObjectStore)`，构造 `(self, *, durable: ObjectStore, ephemeral: ObjectStore)`。
  - `prepare_upload(filename, purpose, *, content_key=None, tier="durable")`：tier=="ephemeral" 路由到 ephemeral.prepare_upload，否则 durable。返回的 ObjectRef.uri 自带子 store 的 bucket（ephemeral store 用独立 bucket 名如 `cutagent-ephemeral`，便于读时路由）。
  - `put_bytes/get_bytes/exists/signed_url/_path`：按 ref.bucket（或 uri 的 bucket 段）判断属于哪个子 store 再委派。durable bucket vs ephemeral bucket 区分。
  - 新增 `delete(uri: str) -> None`：路由到对应子 store 删除该对象（见 B）。
- A2 `ObjectStore` 基类加 `def delete(self, uri): raise NotImplementedError`；`LocalObjectStore.delete` 删文件 +（空则）父目录；`S3ObjectStore.delete` 调 `delete_object`（+ 删本地 cache 文件）。
- A3 `prepare_upload` 基类签名加 keyword `tier: str = "durable"`（Local/S3 忽略它即可，保持兼容）；只有 TieredObjectStore 真正按 tier 路由。

### B. store_file 传 tier + 删除入口

- B1 `packages/media/assets.py` `store_file(object_store, path, *, purpose, addressed=False, tier="durable")`：把 tier 透传给 prepare_upload。默认 durable（向后兼容，其余调用点不变）。
- B2 digital_human.py **仅两处**改 `tier="ephemeral"`：line 1897 portrait_track、line 2040 rendered。其余 store_file 不动（默认 durable）。

### C. get_object_store 构造分层 + 配置

- C1 `object_store_from_env()`：先按现有逻辑建 durable store（local/s3）；再建 ephemeral=LocalObjectStore(root=临时目录, bucket="cutagent-ephemeral")，包成 `TieredObjectStore(durable=…, ephemeral=…)` 返回。ephemeral 根从 `CUTAGENT_OBJECTSTORE_EPHEMERAL_PATH` 读，默认系统临时目录下 `cutagent-ephemeral`（`tempfile.gettempdir()`），**不要落在仓库 .data 里**（省盘 + 不被 git 跟踪）。
- C2 可用 `CUTAGENT_OBJECTSTORE_TIERED=0` 关闭分层（回退为纯 durable，兼容/排障用）；默认开启。

### D. run 成功后清理中间产物（用完即删）

- D1 在 `_finalize_run_report`（约 line 2237，仅成功路径走到）末尾：遍历 `state.artifacts` 中 tier=ephemeral 的 kinds（`video_portrait_track`、`video_rendered`），对每个 artifact.uri 调 `get_object_store().delete(uri)`；删除失败只 log warning 不阻断（best-effort）。把这组 ephemeral kinds 定义在一处常量（如 `_EPHEMERAL_ARTIFACT_KINDS`）。
- D2 失败 run 不到 finalize → 中间文件留存供 retry/resume；这是期望行为，不要在失败路径删。
- D3（不做）跨 run 的 ephemeral 残留 GC：本地临时目录本就小且可被系统清理；M6k 的 scripts/gc_objectstore.py 可后续扩展，本批不碰。

## 边界（Out of scope）

- 不改 provider 插件、不改 OSS 上传 multipart（M6N 已做）、不碰前端。
- audio_tts 保持 durable（ASR 经签名 URL 取、HeyGem 落地再传，都需要它在 durable）。
- 不动 reuse 语义（缺失中间产物→重跑节点，已是现状）。

## 测试

- D1 TieredObjectStore 单测：put(tier=ephemeral) 落 ephemeral store、put(tier=durable) 落 durable；get/signed_url/exists 按 bucket 正确路由；delete 删对应 store。用注入 fake/Local 两个子 store。
- D2 store_file(tier=) 透传单测；object_store_from_env 默认返回 TieredObjectStore、CUTAGENT_OBJECTSTORE_TIERED=0 返回纯 durable。
- D3 pipeline 单测：一条成功 run 后，video_portrait_track/video_rendered 的对象被删除（ephemeral 清理），video_final/subtitle/cover 仍在 durable。复用现有 in-memory/local pipeline 测试夹具。
- D4 全量基线不回退（约 188）。所有 pytest 包 `timeout -k 5 600`，主仓 venv。

## 验收门（验收官）

1. 演示 OSS 后端 + 本批：跑 strict 真人声 run，**渲染明显加快**（中间产物不再传上海），成片成功；run 后 ephemeral 临时目录中该 run 的 portrait_track/rendered 已删，OSS 上只有 final/subtitle/cover/audio。
2. 仓库 `.data` 与 OSS 都不再堆积中间大视频。
3. 全量 + DB + Temporal 三套绿。
