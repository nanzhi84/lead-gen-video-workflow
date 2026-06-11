# M6b 施工简报：真媒体处理链路

负责：Codex（执行）/ Claude（架构 + 验收）
分支：`feat/m6b-real-media`
Spec：1A.7（FFmpeg/确定性媒体传感器）、第 7 章节点契约（7.5 TTS、7.7 对齐、7.12 PortraitTrackBuild、
7.14 RenderFinalTimeline、7.15 SubtitleAndBgmMix、7.16 Export）、2.3 不允许静默降级。
目标：**不依赖外部 API key**，把 sandbox 流水线的媒体环节换成真实 FFmpeg 实现——跑完一条 run
产出真实可播放的 mp4（无真人语音/口型，但时长/画面/字幕/混音全部真实）。真 TTS/lipsync/VLM 是 M6d。

## 环境（验收官已确认）

- `ffmpeg/ffprobe 7.0.2-static` 在 `/home/nanzhi/.local/bin/`（codex sandbox 内可执行，无网络需求）。
- 路径经 settings 配置：`CUTAGENT_FFMPEG_BIN`/`CUTAGENT_FFPROBE_BIN`（默认 PATH 查找）。
- 所有 ffmpeg 调用封装在 `packages/media/video/ffmpeg.py`（subprocess + 超时 + 结构化错误映射到
  ErrorCode.render_failed 等），禁止散落 shell 拼接；命令行参数列表传递，不走 shell=True。

## 改动清单

### A. 媒体探针与工具层（packages/media/video, packages/media/assets）

- A1 `probe_media(path) -> MediaInfo`：ffprobe JSON 解析（duration/width/height/fps/codec/format/
  sample_rate/channels），替换所有手填 MediaInfo 的地方；URI-only artifact 落盘时必须真探针 + 真 sha256。
- A2 缩略图真实现：上传完成与成片导出用 ffmpeg 抽帧（首帧+中点帧），thumbnail artifact 带真 MediaInfo。
- A3 合成测试素材生成器 `tests/fixtures/media.py`：用 ffmpeg lavfi 生成确定性测试视频
  （testsrc2 彩条+timecode，竖屏 1080x1920，5/10/30s 各档）与测试音频（sine/anoisesrc），
  conftest session 级缓存生成（不入 git 大文件）。

### B. Sandbox TTS 产出真实音频（packages/ai/providers sandbox + packages/media/audio）

- B1 sandbox TTS 不再返回假引用：按脚本长度估算时长（中文 ~4.5 字/秒 × voice speed），用 ffmpeg
  生成真实 WAV（16kHz mono，正弦+静音节拍可区分段落），artifact 带真 MediaInfo + sha256。
  注：这是「真文件、合成内容」，billing 仍走 sandbox 不计价；provider 接口契约不变。
- B2 NarrationAlignment：基于脚本标点切句 + 按字数比例切分真实音频时长 → `narration.units`
  来源标记 `estimated`（spec 7.7 顺位 4），strict 模式拒绝逻辑保持（M1 已修真）。
  TTS 字幕/forced alignment/ASR 顺位留 M6d。**golden #1 等用例需把 strict_timestamps 调整为
  允许 estimated 的配置或显式非 strict**——按 spec 语义改 fixture，不许放宽契约。

### C. PortraitTrackBuild 真切片（spec 7.12）

- C1 按 plan.portrait 的 source window 用 ffmpeg 帧精确切片（-ss/-to 输出帧对齐，统一转码到
  1080x1920@30fps 中间格式），concat demuxer 拼接，产出真 `video.portrait_track`。
- C2 拼接后 ffprobe 校验总时长与 plan 误差 ≤1 帧，超差 hard fail `render.invalid_timeline`；
  source window 越界在切片前校验，hard fail。
- C3 sandbox lipsync 保持 pass-through（输出=输入 portrait track，skipped 标记），真 lipsync 是 M6d。

### D. RenderFinalTimeline 真渲染（spec 7.14）

- D1 按 plan.render 合成：主轨 + B-roll overlay（按 timeline_start/end_frame 精确插入，overlay
  缩放裁切到画幅），输出真 `video.rendered`。不烧字幕、不混 BGM（spec 红线）。
- D2 渲染后探针校验：总帧数与 plan.total_frames 一致，分辨率/fps 符合 render_size。

### E. SubtitleAndBgmMix 真实现（spec 7.15）

- E1 ASS 字幕真生成：narration units → ASS（样式按 plan.style 的 SubtitleStylePlan：字号/位置/
  style_preset 映射到 ASS 样式），ffmpeg subtitles filter 烧制；字幕失败= render.subtitle_failed
  hard fail（除非用户关闭字幕）。
- E2 BGM 真混音：bgm 素材按 BgmPlan 音量 amix（音频时长对齐主轨，循环或截断），auto_mix 时
  人声侧链兜底可简化为固定配比；BGM 不可用 soft degrade（已有语义保持）。
- E3 产出真 `video.final` + `subtitle.ass` artifact（真文件真探针）。

### F. Export 与全链验证（spec 7.16）

- F1 ExportFinishedVideo：真 mp4 落 objectstore、真封面帧（CoverOptions.frame 模式 ffmpeg 抽帧）、
  FinishedVideo.duration_sec 用探针值。
- F2 golden 媒体断言增强：#1 最小成功用例断言产物 mp4 可探针、时长≈TTS 音频时长、分辨率 1080x1920、
  含音轨；#9 字幕用例断言 ASS 文件非空且烧制后视频帧不同于未烧制（或探针 stream 校验）。
- F3 Temporal 集成（门控）用真媒体链路跑通一条 run（时长几秒的小素材，控制 CI 时间）。
- F4 Demo 种子素材替换为生成的真实小视频（bootstrap 时若 ffmpeg 可用则生成，不可用则 fail-fast
  提示——种子不再是 .txt 假文件）。

## 边界（Out of scope）

- 真 TTS/ASR/forced alignment/VLM 标注/真 lipsync（M6d，需 API key）；
- PySceneDetect/VAD 传感器接入（标注修真时一起，M6d）；剪映草稿包真实化（单列）；
- 性能优化（并行转码等）后续按需。

## Verification（sandbox 内，ffmpeg 可用）

- 全量 pytest（基线 109 passed）+ 新增媒体单测（探针/切片/渲染/字幕各自独立用小素材验证）。
- golden #1/#3/#5/#8/#9 在真媒体链路下全绿（耗时控制：测试素材 ≤10s）。
- OpenAPI 无意外 diff；不碰前端。

## 验收门（验收官执行）

1. 真环境（Temporal+DB+worker）提交一条 run：产出 mp4 本机可播放（探针校验+实际抽帧目检）。
2. 字幕开启/关闭产物差异真实；BGM 混音可听（探针音轨参数变化）。
3. portrait 越界/时长超差用例 hard fail 且错误码正确。
4. 全量 + DB + Temporal 三套绿；run 总耗时在小素材下 < 60s。
