# M6V-B 施工简报：legacy 资产索引迁移脚本 `scripts/migrate_legacy_assets.py`

负责：Codex（写脚本）/ Claude（架构 + 跑迁移 + 验收）
分支：`feat/m6v-b-migration-script`
前置：**M6V-A2 必须先合并**（SQL import 路径支持 uri→uploaded.file artifact + 幂等）。

## 本质（用户已拍板）

**零字节搬运的纯索引迁移**：原系统资产已全在 OSS（`videoretalk-test-bucket` 下 `digital-human-platform/dev/uploads/`），genesis 用同一 bucket。脚本读原系统索引 → 构造现成 OSS uri → 调 genesis import API 建 Case/Script/MediaAsset(+uploaded.file artifact 指向 OSS)。**不下载、不上传、不复制任何二进制**。

范围：**3 个 dev case + 创作素材库**：
- 3 case 业务上下文（cases.json）+ 5 候选脚本（candidate_scripts.json）
- 共享库：12 BGM、fonts、templates_pool、cover_templates
- 每 case 的 broll（per-case broll/library.json）+ portrait（见下）

## 已勘定事实（数据源 + 结构，勿推翻）

- **OSS 前缀**：所有资产 key = `digital-human-platform/dev/uploads/<relpath>`，uri = `s3://videoretalk-test-bucket/digital-human-platform/dev/uploads/<relpath>`。OSS 上 `dev/config/` **为空**——case/script 元数据**不在 OSS**，只在 mac mini。
- **元数据来源（脚本入参 `--case-meta-dir`，验收官从 mac mini 只读导出后提供）**：
  - `cases.json`：list，每项 `{id, name, industry, target_audience, key_selling_points[], ip_persona, product_name, description, ...}`（3 个 case：da9fd786 无忧快喷 / 96707ac3 三只喜鹊 / 213f4e42 龙哥轮毂）。
  - `candidate_scripts.json`：list 5，每项 `{id, content, case_id, case_name, scene_type, tags[]}`。
- **资产索引来源（脚本从 OSS 读，单一真相源）**：
  - `bgm_library/library.json`：`{tracks:[{id,name,filename,path:"uploads/bgm_library/<f>.mp3",duration,...}]}`，11 首，全局（case_id=None）。
  - per-case `cases/<uuid>/broll/library.json`：`{videos:[{id,filename,path:"cases/<uuid>/broll/videos/<f>.mp4",scene,duration,...}]}`，kind=broll，case_id=<uuid>。
  - `templates_pool/index.json`：dict 90 项，每项 `{id,name,category,duration,path:"video_templates/<f>.mp4",material_type:"portrait"|...,thumbnail,tags,case_id}`。**portrait 素材主要在这里**（material_type=="portrait"→kind=portrait；其余按 material_type 映射，未知归 video/other）。
  - `cover_templates/<uuid>/...png`：per-case 封面模板，kind=cover_template。
  - fonts：`fonts/font_annotations.json` + `fonts/{subtitle,system,user}/` 下字体文件，kind=font（解析 font_annotations.json 取字体清单；结构脚本里探明，缺失字段给安全默认）。
- **uri→OSS key 规则**：索引里的 `path` 形如 `uploads/bgm_library/x.mp3` 或 `cases/<uuid>/broll/videos/x.mp4` 或 `video_templates/x.mp4`。**统一 OSS key = `digital-human-platform/dev/uploads/` + path 去掉开头多余的 `uploads/`**（注意 bgm 的 path 带 `uploads/` 前缀，broll/templates 不带——脚本要规范化：剥掉前导 `uploads/` 再统一加 `digital-human-platform/dev/uploads/`）。脚本**必须对每个构造出的 key 做 OSS head_object 校验**，不存在的跳过并记 WARN（不静默）。
- genesis import 契约：`POST /api/import/batches`，body `{import_type, rows:[...]}`。import_type ∈ case/script/media。
  - case row：`{name, industry?, product?, target_audience?, ...}`（对齐 SQL `_create_import_row` case 块字段；id 由 genesis 生成——**但要保留原 case 关系**：见下「id 映射」）。
  - script row：`{case_id, title, script}`。
  - media row（M6V-A2 后支持）：`{case_id?, kind, title, uri, mime?, sha256?, duration_sec?, width?, height?, external_id?}`。

## id 映射（关键，别丢关系）

- genesis import 给 case/script 生成新 id（internal_id），原 uuid 不直接当主键。脚本要**维护 原 case uuid → genesis case_id 的映射**：先 import 3 个 case 拿回 genesis case_id（ImportRowResult.internal_id），再用该映射给 script.case_id 和 per-case media.case_id 填 genesis case_id。global 库（bgm/fonts/templates_pool 非 case 绑定项）case_id=None。
- 用 `external_id` 透传原 id 便于追溯/幂等。

## 脚本要求

- `scripts/migrate_legacy_assets.py`，CLI：`--case-meta-dir <dir>`（含 cases.json/candidate_scripts.json）、`--api-base http://127.0.0.1:8021`、`--cookie <session>` 或登录参数、`--dry-run`（默认，只打印计划：每类多少行、样例 uri、OSS 校验结果）、`--apply`（真调 import）、`--kinds`（可选筛选 case,script,bgm,broll,portrait,font,cover）。
- OSS 配置从 env（复用 `object_store_from_env` / 既有 env 变量）读，head_object 校验 key 存在。
- 幂等：依赖 M6V-A2 import 幂等；脚本自身也应可重复跑（同 external_id/uri 不重复）。
- 失败显式：构造不出 uri、OSS key 不存在、import 返回 failed → 汇总报告，不静默吞。
- **纯迁移工具，不碰 pipeline/不触发出片/不改 genesis 业务代码**；只读 mac mini（实际只读本地 --case-meta-dir，脚本不 SSH）。

## 测试

- 脚本逻辑单测（mock OSS head_object + mock import API）：cases.json→case rows、candidate_scripts→script rows（case_id 经映射）、bgm/broll/templates path→正确 OSS uri、id 映射正确、OSS key 缺失被跳过记 WARN、dry-run 不发请求。**不联网、不真调 OSS/API**。
- 全量基线不回退；pytest `timeout -k 5 600`。

## 验收门（验收官，live）

1. `--dry-run` 打印 3 case + 5 script + 11 bgm + 各 case broll + portrait/templates + fonts + cover 的计划，OSS key 校验全绿。
2. `--apply` 后：genesis DB 有 3 真实 case（业务上下文）+ 5 脚本 + 各类 MediaAsset，media 的 source artifact uri 全是 `s3://.../digital-human-platform/dev/uploads/...`；素材库/案例工作台显示真实资产，签名 GET 能播。
3. 重跑 `--apply` 幂等（全 skipped）。
4. 全量 + tsc/build（若动前端，预计不动）绿。

## 边界

- 不迁 prod；不迁 outputs/成片（用户选 3case+素材库，成片本批不做）；不迁 cache/annotations 的 VL 标注（标注是 pipeline 产物，本批只迁素材本体；annotation 可后续）。
- 不下载/上传二进制。
