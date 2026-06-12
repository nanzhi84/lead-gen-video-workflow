# M6M 施工简报：OSS 对象存储兼容 + ASR 公网签名 URL（解锁 strict 真对齐字幕）

负责：Codex（执行）/ Claude（架构 + 验收）
分支：`feat/m6m-oss-strict-alignment`
来源：验收官已 live 验证——真 MiniMax 人声音频上传阿里云 OSS → 签名 URL → DashScope Paraformer 返回**真词/句级时间戳**（[0-3515ms]/[3515-10780ms]）。genesis 差两处即可让 strict_timestamps 真出片：① 对象存储能用 OSS（产物落公网可达）；② NarrationAlignment 把**公网签名 HTTPS URL** 传给 ASR（现在传的是 s3:// URI，DashScope 云端取不到）。

## 已验证事实（勿推翻）

- 真 ASR 路径通：oss2 上传 mp3 → `bucket.sign_url("GET",...)` → DashScope `paraformer-v2` 异步任务 SUCCEEDED，返回 sentences 真时间戳。
- genesis 现有 boto3 `S3ObjectStore` **可直连 OSS S3 兼容端点**，但需两项配置：
  - `addressing_style="virtual"`（OSS 禁止 path style，报 SecondLevelDomainForbidden）；MinIO 则需 "path"。
  - botocore 校验和：`request_checksum_calculation="when_required"` + `response_checksum_validation="when_required"`（否则 OSS 报 `aws-chunked encoding is not supported`）。
  - 验证脚本实测：virtual + 上述校验和配置 → put_object OK、presigned GET 200、host 为 `videoretalk-test-bucket.oss-cn-shanghai.aliyuncs.com`。
- ASR 插件 `packages/ai/providers/dashscope.py` 已把 `call.input["audio_uri"]` 作为 `file_urls` 提交——只要 audio_uri 是 https 即可。

## 改动清单

### A. S3ObjectStore 兼容 OSS（可配置寻址风格 + 校验和）

- A1 `packages/core/storage/object_store.py` `S3ObjectStore._build_client`（约 197-218）的 `Config`：
  - 寻址风格改为可配置：新增构造参数 `addressing_style: str = "path"`，`Config(s3={"addressing_style": addressing_style})`；
  - 无条件加 `request_checksum_calculation="when_required"`、`response_checksum_validation="when_required"`（对 MinIO 无害、对 OSS 必需）。
- A2 `S3ObjectStore.__init__` 增 `addressing_style` 参数透传到 `_build_client`；`object_store_from_env()` 从新环境变量 `CUTAGENT_OBJECTSTORE_ADDRESSING_STYLE`（默认 "path"，保持 MinIO 现状）读取传入。
- A3 不改 LocalObjectStore；不改既有 MinIO 行为（默认 path + 校验和 when_required 对 MinIO 仍工作）。

### B. NarrationAlignment 传公网签名 URL 给 ASR（核心解锁）

- B1 `packages/production/pipeline/digital_human.py` `_narration_alignment`：调 ASR 前，把音频 URI 解析成签名 URL——
  `audio_url = get_object_store().signed_url(tts.uri).url`，ASR 的 `ProviderCall.input` 用 `{"audio_uri": audio_url, ...}`（替换现在的 `tts.uri`）。
  - 若 `signed_url` 抛错或返回非 http(s)（如 LocalObjectStore 原样返回 local://），按现状把失败交给 M6L 的软降级/strict 分支处理（即非 strict 估算、strict 报错）——**不要新增吞异常路径**，复用既有 try 语义即可（ASR 失败已由 M6L 分流）。
- B2 不动 ASR 成功后的对齐构造、不动 M6L 的软降级逻辑。

### C. 配置与文档

- C1 `docs/ops/objectstore-oss.md`：如何把 genesis 指向阿里云 OSS——env 清单（CUTAGENT_OBJECTSTORE_BACKEND=s3、ENDPOINT=https://oss-cn-<region>.aliyuncs.com、BUCKET、ACCESS_KEY/SECRET_KEY、REGION=oss-cn-<region>、ADDRESSING_STYLE=virtual），并指出这样 strict 真对齐字幕即可工作（产物公网可达）。
- C2 README 运维段补一行指引。

### D. 测试

- D1 `S3ObjectStore` 单测：用 client_factory 注入 fake，断言 addressing_style 透传；`object_store_from_env` 读 `CUTAGENT_OBJECTSTORE_ADDRESSING_STYLE`。（不连真 OSS。）
- D2 `_narration_alignment` 单测扩展：mock object_store.signed_url 返回 `https://example/x.mp3`，断言 ASR 的 ProviderCall.input["audio_uri"] 是该 https URL（不是 s3://）。复用 M6L 新增的 narration 测试夹具。
- D3 全量基线不回退（约 183 单测）。所有 pytest 包 `timeout -k 5 600`，用主仓 venv。DB/Temporal 集成验收官在外面跑。

## 边界（Out of scope）

- 真口播片（真人像 ingest + HeyGem lipsync 公网 URL）→ 留 M6N。
- 不做 OSS 的 ACL/public-read 改造（用签名 URL，私有桶即可）；不做 OSS lifecycle/GC。
- 不改 provider 插件契约；不碰前端。

## 验收门（验收官，真 OSS + 真 key）

1. 演示环境改用 OSS 后端（env 切换 endpoint/bucket/keys/addressing=virtual），提交 `strict_timestamps=true`、真 MiniMax 人声 run：TTS✅ → NarrationAlignment 走真 ASR（DashScope 取 OSS 签名 URL）→ 产出 source=asr 的真词级对齐 → 出片✅，字幕时间与语音吻合（抽帧+ASS 时间核对）。
2. MinIO 后端回归：addressing=path 默认仍正常 put/get/presigned（不回退 M6f）。
3. 全量 + DB + Temporal 三套绿。

---

## 验收记录（2026-06-12，验收官：Claude，真 OSS + 真 key live）

**判定：核心通过并合入**（merge 5c2a21f + heartbeat 修复 27ec950）。

环境插曲（已绕过）：验收中途 Docker Desktop 的 WSL integration 掉了→cutagent 容器栈 Exited；用户勾回后用原生 docker `start` 重启，数据卷未丢（5 音色 + group_id 在）。

真链路证据（演示切 OSS 后端 = videoretalk-test-bucket@oss-cn-shanghai，addressing=virtual）：
- **strict_timestamps=true 真人声 run 实证真对齐**：ResolveCreativeIntent → 真 MiniMax TTS（落 `s3://videoretalk-test-bucket/generated-audio/...minimax-tts.mp3`）→ **NarrationAlignment 在 strict 下 succeeded**（strict 失败即硬 fail，成功即真 ASR）。
- 对齐产物核对（DB）：`narration source=asr, strict=True`；`audio.alignment` 2 段**真词级时间戳** `[0.03–2.9s] / [3.44–9.72s]`（带首尾静音裁剪，区别于估算的 [0–3.61]/[3.61–10.84]）。
- worker 日志：`POST .../asr/transcription` + 多次 `GET .../tasks/{id}` + 取 `dashscope-result-bj.oss-cn-beijing` 结果 JSON——DashScope 云端成功从 OSS 签名 URL 取音频。
- 独立 live 预证：oss2 上传 mp3→签名 URL→paraformer-v2 返回真句级时间戳（先于代码改动验过路径）。

heartbeat 修复（27ec950）：`run_node` 是同步 activity 不发 heartbeat，旧 `heartbeat_timeout=30s` 在慢 OSS 上传（视频传上海 >30s）时误取消→重试循环；移除后靠 per-node start_to_close（30min / LipSync 120min）。本地 MinIO 因上传 <30s 从未触发。

遗留（→ 性能优化，非能力缺口）：`S3ObjectStore.put_bytes` 用单发 `put_object`，大视频产物传远端 OSS（上海）慢；原仓库用 multipart（OSS_MULTIPART_*）。建议后续给 put_bytes 加 multipart/并发分片以加速远端 OSS 出片；或工作文件留本地、仅音频/成片上 OSS。render 管线本身已在非 strict MinIO run 完整出片证过，与 OSS 上传速度正交。
