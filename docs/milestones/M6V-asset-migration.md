# M6V 施工简报：历史资产迁移 + OSS 索引（Mac mini dev → genesis）

负责：M6V-A 代码 Codex（执行）/ M6V-B 迁移运行 Claude（验收官，live ops）/ Claude（架构）
分支：`feat/m6v-asset-migration`
来源：用户「做完 5 个缺口后帮我建立索引，把 OSS 的资产链接迁移过来；真实运营数据去 mac mini 的 dev 侧找（只读，不影响生产）」。

## 已勘定事实（Mac mini dev 只读勘察 2026-06-13）

- 访问：`ssh wzm-lan`（Tailscale → Mac-mini.local, Darwin）。dev 根 `~/digital-human-deploy/dev/data`；**prod `~/digital-human-deploy/prod/data` 绝不碰**。
- 真实运营数据（dev）：
  - **3 个 case**（`config/workbench/cases.json`）：无忧快喷 `da9fd786`、三只喜鹊 `96707ac3`、龙哥轮毂 `213f4e42`，含完整业务上下文（industry/target_audience/key_selling_points/ip_persona/product_name…）。
  - **5 条候选脚本**（`config/workbench/candidate_scripts.json`）。
  - 每 case 目录 `uploads/cases/<uuid>/`：`portrait/`（真人像）+ `broll/{videos,annotations}/`（broll 视频 + VL 标注 json）。
  - **12 BGM**（`uploads/bgm_library/*.mp3`，88M，文件名带 hash 后缀）。
  - **fonts 6**（`uploads/fonts`，56K）、cover_templates/covers（png）、templates_pool 210 json（broll/标注模板）。
  - 资产合计 uploads ≈ 1.1G（cases 1.0G 为主：40 mp4 + 11 mp3 + png + 标注 json）。
  - `config/case_selections.sqlite3`（原版选材账本，57K）——M6T 的历史可选迁移源（forward-looking 的 selection_ledger 不强依赖它）。
  - `config/system_prompts.json`（38K）——M6R 已据原版默认 seed，**不重复迁**。
- genesis 侧已具备：分层 ObjectStore（OSS durable + 本机 MinIO ephemeral，内容寻址幂等）；`POST /api/import/batches`（M6P 增强：case/script/media/finished_video/... → 落真行）；`probe_media`（packages/media）；素材库前端。
- **已知缺口**：media import_type 建 MediaAssetRow 但**不建** source `uploaded_file` artifact（kind 值 `uploaded.file`，注意点号），也不 probe。迁移要让 import 自洽。

## M6V-A 代码（Codex）：让 import 具备迁移能力

- A1 media import 行增可选字段：`uri`（OSS s3://…）、`title`、`mime`、`sha256`、`duration_sec`、`width`/`height`（均可空）。当 media import 带 `uri`：
  - 自动建 source artifact `kind='uploaded.file'`（**点号值，勿用 uploaded_file**），uri=该 OSS uri；
  - 对可探测媒体跑 `probe_media` 补 dims/duration（探测失败 best-effort 不阻断，用传入元数据兜底）；
  - 再建 MediaAssetRow，`source_artifact_id` 指向上面 artifact。
  - 幂等：同 (case, kind, sha256/uri) 重复 import 不重复建（content-addressed）。
- A2 OSS 索引读端点（轻量）：`GET /api/library/assets?case_id=&kind=` 已有则复用；若需「迁移索引」视图，加 `GET /api/import/migration-manifest`（或落一份 manifest 资产）返回 legacy_key→oss_uri→asset_id 映射。**不新增重表**，能从既有 MediaAsset + artifact 推导就推导。
- A3 测试：import 带 uri → 建 uploaded.file artifact + MediaAsset + 幂等单测（mock probe）；契约/openapi/schema.d.ts 同步；全量不回退；pytest 全 `timeout -k 5 600`。
- 约束：不碰 pipeline 真出片、不碰发布；单文件 ≤400 行。

## M6V-B 迁移运行（Claude 验收官，live ops，不进 Codex sandbox）

一次性迁移脚本 `scripts/migrate_legacy_assets.py`（可由 Codex 写、验收官跑），流程：

1. **只读拉取**：`rsync`/`scp` 从 Mac mini dev（`uploads/cases/*`、`bgm_library`、`fonts`、`cover_templates`）→ 本机 staging（**只读 Mac mini，不改 dev/prod**）。
2. **上 OSS durable**：每个二进制资产内容寻址（sha256 key）上传 OSS durable bucket（幂等 skip-if-exists，复用 M6k-D/M6M 路径）。
3. **建 manifest**：JSON 映射 `legacy_path → {oss_uri, kind, case_id, sha256, mime, duration, dims}`；case/script 从 cases.json/candidate_scripts.json 转 genesis 契约。
4. **调 import**：`POST /api/import/batches` 喂 manifest → 建 Case + Script + MediaAsset(+uploaded.file artifact) 全部指向 OSS。
5. **验收**：素材库前端显示真实 BGM/broll/portrait（OSS 回放）；3 个 case 显真实业务上下文 + 脚本；asset 的 uri 为 s3://（非 local://）。

## 验收门（验收官）

1. M6V-A 全量 + 契约 + tsc/build 绿；import 带 uri 真建 uploaded.file artifact + MediaAsset（幂等）。
2. 迁移跑完：OSS durable 里有 12 BGM + 3 case 的 portrait/broll；DB 有 3 真实 case + 5 脚本 + 对应 MediaAsset，uri 全 s3://。
3. 前端素材库/案例工作台显示迁移来的真实资产，可定位 OSS。
4. 全程 Mac mini 只读，prod 零触碰。

## 边界

- 不迁 system_prompts（M6R 已 seed）；case_selections 历史账本可选、非必须。
- 不迁 prod；不迁 temp/cache/logs/backups（非资产）。
- 不在迁移里跑 pipeline 真出片（迁的是素材，不是成片重算）。
