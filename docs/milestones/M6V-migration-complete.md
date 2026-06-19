# M6V 资产迁移完成记录（纯索引迁移，零字节搬运）

负责：Codex（脚本 M6V-A/A2/B/B2/B3/B4）/ Claude（架构 + 跑迁移 + 验收）
完成日期：2026-06-13

## 本质
用户洞察「资产本就在 OSS，直接带索引」正确。原系统资产全在同一 bucket `videoretalk-test-bucket` 的 `digital-human-platform/dev/uploads/` 下。迁移 = 读原索引 → 构造**现成 OSS uri** → genesis import 建 Case/Script/MediaAsset(+uploaded.file artifact 指向 OSS)。**零下载/零上传/零复制**。

## 迁移成果（demo DB，全部 OSS-backed、幂等）

| 类型 | 数量 | 说明 |
|---|---|---|
| **真实运营 case** | 3 | 无忧快喷 / 三只喜鹊 / 龙哥轮毂（完整业务上下文）|
| 脚本 | 5 | candidate_scripts |
| BGM | 11 | bgm_library（全局）|
| 封面模板 | 3 | cover_templates（1 个 case-1 遗留正确判失败）|
| **broll 视频** | 18 | per-case broll/videos（OSS 上实有 18，索引引用的其余 96 不在 OSS→WARN-skip）|
| **portrait 模板** | 199 | templates_pool（203 条，4 个 OSS key 缺失→WARN-skip）|

全部 media 带 `uploaded.file` artifact 指向 `s3://videoretalk-test-bucket/digital-human-platform/dev/uploads/...`，签名 GET 可播；重跑全 skipped（幂等）。

## 脚本演进（live dry-run 逐个暴露真实数据形态，逐个修）
- M6V-A/A2：import 支持 uri→uploaded.file artifact（in-memory + SQL 双路径 + 幂等）
- M6V-B：迁移脚本 scripts/migrate_legacy_assets.py（可注入 OSS/HTTP，dry-run/apply）
- M6V-B2：broll 命名目录 `cases/{name}_{uuid8}/`、fonts 丢弃（OSS 无字体文件）
- M6V-B3：可重跑——按 name 从 GET /api/cases 补建 uuid→genesis case_id 映射、case 按 name 幂等
- M6V-B4：templates_pool 是 `{"templates":[...]}` wrapper（非 dict-by-id），修迭代

## 边界（诚实）
- broll 索引引用的视频多数（96/114）不在 OSS——数据现实，脚本 WARN-skip 不伪造。
- fonts 无 OSS 文件（仅标注+预览），不迁。
- 未迁 prod、未迁 outputs/成片（用户选 3case+创作素材库）。
- cases 表无 external_id，迁移按 name 关联（3 个 case 名唯一）。
