# M6g 施工简报：媒体深加工（防抖 + 无效片段裁剪 + 自动匹配替换）

负责：Codex（执行）/ Claude（架构 + 验收）
分支：`feat/m6g-media-deep`
依据：parity-check 坦白②媒体补做。ffmpeg 7.0.2 在 sandbox 可用（M6b 验过）。剪映真包最复杂，单列 M6h。

## 原版参考（只读 `/home/nanzhi/projects/digital-human-Cutagent/backend/app/`）
- 防抖/增稳：`utils/upload_video_normalizer.py`（vidstabdetect→vidstabtransform 两遍流水线、参数常量）
- 无效片段裁剪：`services/broll_analyzer/segment_trimmer.py`（trim_invalid_segments：按有效片段裁剪拼接）
- 自动匹配替换：`pages/Templates.tsx` 批量上传的"自动匹配替换"模式 + 后端按文件名匹配保留原标注
- 抄算法/ffmpeg 参数，不抄架构。

## 改动清单

### A. 视频防抖/增稳（packages/media/video）
- A1 `stabilize_video(path) -> path`：ffmpeg vidstabdetect（生成 transforms.trf）+ vidstabtransform 两遍，
  参数照原版 upload_video_normalizer.py（smoothing/shakiness 等）；统一封装在 ffmpeg 工具层。
- A2 上传规范化可选开关：portrait/broll 上传 complete 时若 `stabilize=true`（PrepareUploadRequest 加可选字段）
  则增稳后再落库；MediaAsset 标记已增稳。
- A3 批量增稳端点 `POST /api/media/assets/batch-stabilize`（operator，按 asset_ids，异步或同步小批）。
- A4 前端素材库模板 tab：上传弹窗"轻微抖动启用防抖"开关 + 批量操作"增稳"按钮（去掉 R3 的禁用态）。

### B. 无效片段裁剪（packages/media/video + annotation）
- B1 `trim_to_valid_segments(path, segments) -> path`：按标注的有效片段（AnnotationTimelineRow/质量事件
  判定的 valid 区间）ffmpeg 帧精确切片 + concat，产出裁剪后视频；越界/空有效区按 spec 2.3 hard fail。
- B2 标注编辑器"裁剪无效片段"动作接真实现（R3 占位 → 真 ffmpeg 裁剪），裁剪后重算有效时长、生成新 artifact。
- B3 端点 `POST /api/annotations/{asset_id}/trim`（operator），前端标注弹窗 Scissors 按钮接上。

### C. 模板自动匹配替换（apps/api + 前端）
- C1 批量上传"自动匹配替换"模式：按文件名匹配现有模板，matched 的替换源视频 + **保留原 canonical 标注**，
  unmatched/ambiguous 如实报告（不静默）；后端端点 + 前端上传弹窗 radio（新增 vs 替换）。
- C2 卡片"替换原视频"单项操作（隐藏 file input → UploadSession → 替换源 + 保留标注）。

## 边界
- 剪映草稿真包（轨道/SRT/贴纸）→ M6h；真 portrait+HeyGem 完整真口播片 → 等用户素材；M6c 冻结。

## Verification（sandbox 内，ffmpeg 可用）
- 全量 pytest 绿（基线含 M6f）；防抖/裁剪用 tests/fixtures/media.py 合成素材验（探针确认输出有效、时长符合预期）；
  `cd apps/web && npx tsc --noEmit && npm run build` 绿；OpenAPI 同步。

## 验收门（验收官）
1. 上传抖动测试视频→增稳→探针确认输出可播、参数生效；批量增稳。
2. 标注标无效区→裁剪→输出时长=有效区总和、帧精确、内容正确（抽帧）。
3. 自动匹配替换：同名上传替换源保留标注；unmatched 如实报告。
4. 全量 + DB + Temporal 三套绿。

---

## 验收记录（2026-06-12，验收官：Claude）

**判定：通过并合入**（merge 见 git log）。证据：全量 + tsc/build 三绿；**真 ffmpeg 抽查**：合成 4s 测试视频经 `stabilize_video` 输出时长保持 4.0s；`trim_to_valid_segments([1,3])` 精确得 2.0s。新增 4 端点（batch-stabilize / annotations trim / replace-source / auto-match-replace），越界→render.invalid_timeline、空有效区→material insufficient、替换 matched/unmatched/ambiguous 如实报告。前端防抖开关/批量增稳/裁剪/替换入口接通（去 R3 禁用态）。

合并流程备忘：merge 前必须先 `git fetch <clone> branch:branch -f` 更新主仓库分支 ref（与 merge 串一条命令时若前段被信号中断会漏 fetch，导致 "Already up to date" 空合）。
