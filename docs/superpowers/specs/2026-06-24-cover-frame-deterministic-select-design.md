# 封面参考帧：确定性人脸打分选帧（替换 VLM 选帧）

- 日期：2026-06-24
- 状态：设计已认可，待落 writing-plans
- 关联记忆：[[cutagent-ai-cover-llm-title]]（PR#54 默认 AI 封面 + 成片 LLM 真标题）、[[cutagent-editing-deterministic-vs-llm]]（确定性 vs LLM 分工）、[[cutagent-frame-exact-render]]

## 1. 背景与问题

工作区有一批未提交 WIP，在 PR#54（已合 main，commit `a331fca`）基础上继续做「封面 + 标题全 AI 自动化」。WIP 已实现三件事的骨架：

- VLM 选最佳人像帧当生图参考（`export_finished_video.py` `_select_cover_source_frame_with_vlm`）；
- 选中帧/上传模板拼参考板，经 `openai.image` 走 `/images/edits` 图生图出营销封面（模型自己渲染中文标题）；
- LLM 按脚本总结营销标题（`copy_llm.py` `build_copy_llm_chat`）。

用户实测反馈：**模型直接渲染文字稳定、可接受**；**真正不好的是「VLM 选帧」这一环**。

诊断（均有代码证据）：

1. **候选源头是脏的（最致命）**：`_select_cover_source_frame_with_vlm` 从成片 `video.final` 抽帧。`video.final` 是 `SubtitleAndBgmMix` 烧录 ASS 字幕、上游 `RenderFinalTimeline` 插入 B-roll 之后的产物。抽出的「人像帧」常脸上压着字幕、或干脆是无人 B-roll 空镜。
2. **盲采样**：仅 5 个固定比例点（0.12/0.30/0.50/0.70/0.88），不判断该帧是否真有清晰正脸。
3. **该用的确定性传感器没用**：仓库已有 `sensors/faces.py`（YuNet 人脸检测）、`sensors/cv_quality.py`（Laplacian 模糊检测）。按仓库一贯哲学（确定性出客观信号、LLM 只判语义），应由传感器先筛、不应让 VLM 在烂候选里硬选。

## 2. 决策

- **封面文字仍由生图模型渲染**（保持现状 WIP，本设计不动文字渲染与标题链路）。
- **选帧改为纯确定性人脸质量打分，直选 top1，不用 VLM**。理由：①根因是候选脏 + 盲采样，确定性传感器即可彻底修；②零付费、纯函数可复现、与 spec §2.4「能确定性就别上 LLM」一致；③选帧本质是「最大、最清晰、最居中正脸」的客观问题。
- **已接受的取舍**：YuNet 给不出「睁/闭眼」状态，纯确定性兜不住闭眼瞬间/嘴型怪/表情尬；靠密集采样多给候选摊薄概率。

## 3. 候选源头：避开字幕与 B-roll

在 `ExportFinishedVideo` 节点按优先级选「干净源」artifact（`ArtifactKind`）：

```
video.lipsync  →  退 video.portrait_track  →  退 video.final
```

- `video.lipsync`（口型同步后、烧字幕/插 B-roll 前）：实际出镜的数字人，最贴近成片人物，且干净。优先。
- `video.portrait_track`（口播片段串联，纯脸）：lipsync 缺失时的干净退路。
- `video.final`：两者都缺时的最后退路（行为不弱于现状）。

密集采样与中点兜底**都**在选定的干净源上做。

## 4. 算法：确定性「上镜分」

对干净源密集抽帧，逐帧用 YuNet + Laplacian 打分，全候选取最高分。

### 4.1 采样

- 上限 `N_max = 30` 帧；步长 `stride = max(0.5, duration / N_max)`；在 `[0.1, duration-0.1]` 内均匀取点（避开首尾闪帧）。
- 抽帧用现有 `sensors/frames.extract_frames_for_times`，候选帧 `max_long_side = 720`（够 YuNet + 清晰度判断，控 ffmpeg 成本）。
- 失败/无候选 → 返回 None（兜底）。

### 4.2 单帧打分（取 YuNet 检测到的最大脸）

YuNet 每个检测框 15 值：`[x,y,w,h, 右眼xy, 左眼xy, 鼻尖xy, 右嘴角xy, 左嘴角xy, score]`。

| 子项 | 计算 | 说明 |
|---|---|---|
| size | `face_frac=(w*h)/(W*H)`，理想带 `[0.05,0.30]` 内得 1，带外平滑衰减 | 太小/太满都差 |
| center | `cx=中心x/W`（理想 0.5）、`cy=中心y/H`（理想 0.40，略偏上）；`1 - clamp(2|cx-0.5|)` 与垂直项相乘 | 封面构图 |
| sharp | 脸部裁剪灰度 Laplacian 方差 `v`，`min(1, v/200)`（60=模糊基线口径同 cv_quality） | 越锐越高 |
| frontal | `asym=|dist(左眼,鼻)-dist(右眼,鼻)|/face_w`；`tilt=眼线倾角`；`(1-clamp(asym/0.35))*(1-clamp(tilt/0.5))` | 越正越高 |
| conf | YuNet `score`（已 ≥0.6） | 检测置信 |

加权：`size 0.25 + center 0.20 + sharp 0.25 + frontal 0.20 + conf 0.10`。
**多脸惩罚**：达标脸（两边 ≥ 短边 `min_face_frac`）数量 ≥2（B-roll/镜面反射）→ 该帧弃选（不参与 top1）。
权重/带宽为标定初值，集中为模块常量，便于后续调。

### 4.3 选定与产出

- 全候选最高分 → 记其 `time_sec` 与分项明细（debug/可观测）。
- **再以该 `time_sec` 在干净源上高清重抽一帧**（`extract_frame_at_time`，`max_long_side` 取较高值如 1280）作为送生图模型的参考图 —— 打分用廉价 720px 帧，最终参考图用高清帧。
- 一张达标脸都没有 → 返回 None → 退「干净源中点帧」（沿用现有 `_extract_cover_source_frame`）。

## 5. 代码落点

### 5.1 `packages/media/annotation/sensors/faces.py`（扩展，行为不变）
- 新增 `detect_faces(image, *, score_threshold, min_face_frac) -> list[FaceDetection]`：返回 `bbox=(x,y,w,h)`、`score`、`landmarks`（5×(x,y)）。fail-open 返回 `[]`。
- 重构 `count_faces_in_image` 调 `detect_faces`（计数行为与阈值口径完全不变，受现有测试保护）。

### 5.2 `packages/media/cover_frame.py`（新增模块）
- `score_portrait_frame(detections, frame_wh, sharpness) -> float | None`：**纯函数**，无 IO，承载 §4.2 打分，便于单测。
- `select_best_portrait_frame(video_path, duration_sec, *, temp_dir, n_max=30, candidate_long_side=720) -> BestPortraitFrame | None`：编排采样→检测→打分→取 top1；fail-open（cv2/ffmpeg 缺失、无脸均返回 None）。返回 `time_sec / score / breakdown`，**不含图像字节**（参考图由调用方按 §4.3 高清重抽）。
- 无网络、无付费调用，纪律同 `sensors/`。

### 5.3 `packages/production/pipeline/nodes/export_finished_video.py`（净删 + 改）
- **删除整套 VLM 选帧**：`_select_cover_source_frame_with_vlm`、`_build_cover_frame_select_messages`、`_parse_cover_frame_choice`、`_cover_frame_choice_payload`、`_json_object_from_text`、`_int_from_payload`、`_float_from_payload`、`_cover_vlm_sample_times`、`_resolve_cover_frame_select_prompt_version_id`，以及常量 `COVER_FRAME_SELECT_PROMPT_VERSION_ID`/`COVER_FRAME_SELECT_NODE_ID`/`_COVER_VLM_*`/`_COVER_FRAME_SELECT_*`。
- `_select_cover_source_frame(ctx, copy)` 改为：选干净源 → 调 `select_best_portrait_frame` → 命中则以选定 `time_sec` 高清重抽，构造 `_CoverReferenceImage(selection_source="face_score", source_frame_time_sec=…, selection_reason="确定性人脸打分 …")`；未命中 → 干净源中点帧（`selection_source="midpoint"`）。
- `invocation_ids` 不再被选帧追加（选帧无 provider 调用）；`_generate_ai_cover` 仍只收生图调用 id。
- 模板拼板（`_combine_cover_reference_board`）等逻辑保留不变。

### 5.4 回滚 WIP 的选帧 prompt 种子
- `packages/core/storage/prompt_group_defaults.json`、`packages/core/storage/prompt_groups.py`：删除 `prompt_cover_frame_select` / `prompt_cover_frame_select_v1`（纯确定性不需要）。

### 5.5 `packages/media/CLAUDE.md`
- 在「关键文件」补 `cover_frame.py`（选最佳人像参考帧），faces 章节补 `detect_faces`。

## 6. 测试

- 新增 `tests/media/test_cover_frame.py`：stub `detect_faces` 注入构造检测框，断言 `score_portrait_frame` 与 `select_best_portrait_frame` 选帧偏好——居中 > 偏边、大脸 > 小脸（带内）、单脸 > 多脸（弃）、清晰 > 模糊、正脸 > 侧脸；**不依赖真模型/真 ffmpeg**，确定可复现。
- 改 `tests/production/test_ai_cover_path.py`：
  - 删 `test_ai_cover_uses_vlm_selected_portrait_frame_reference` 及 `_FrameSelectingVlmProvider`/`_seed_vlm_profile`。
  - 其余用例：合成测试视频无真脸 → `select_best_portrait_frame` 返回 None → 干净源中点兜底；现有断言（`source_frame_time_sec==0.5`、`reference_filename=="source-frame.png"`、模板拼板路径）天然保持。
- 硬约束：现有 12 个 `test_ai_cover_path.py` 用例（去掉 VLM 那条后 11 条）保持绿；本地跑需 `PATH=/opt/homebrew/bin`（ffmpeg）+ 空 `CUTAGENT_SECRET_STORE_DIR`。

## 7. 风险与取舍

- 闭眼/嘴型怪/表情尬：纯确定性兜不住（YuNet 无睁闭眼），靠密集采样摊薄。已被用户接受。
- 性能：~30 次抽帧 + YuNet 检测约 2~3s；export 节点本就重 ffmpeg，可接受。后续若慢可改单趟 `fps=` 抽帧优化（本期不做）。
- `video.lipsync` 偶尔可能仍含轻微 overlay？经查 lipsync 在字幕/B-roll 之前，干净；若某部署链路差异导致仍脏，多脸/低分会自然降权，最坏退中点。
- 标定初值（权重/理想带）可能需按真实素材微调；集中为常量，留 follow-up。

## 8. 不在本期范围

- 文字渲染方式（保持模型渲染）；标题/文案 LLM 链路；新增生图 provider；模板花字叠加引擎；睁闭眼/表情的语义级筛选。
