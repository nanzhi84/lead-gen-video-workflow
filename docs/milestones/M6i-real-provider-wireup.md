# M6i 施工简报：真 Provider 业务接通（sqlalchemy 路径 + worker）

负责：Codex（执行）/ Claude（真 key 验收）
分支：`feat/m6i-real-provider-wireup`
背景（验收发现）：M6d 真 provider 插件 + gateway + live 门控都通了（直接调 gateway 真能调 MiniMax/DashScope），
但**业务流程的 sqlalchemy 路径没接真 gateway**，仍走 sandbox 占位：
- `apps/api/services/voices.py:voice_preview` 在 `media_repository is not None`（sqlalchemy 模式）时走
  `media_repository.preview_voice`（sandbox 占位 URI），只有内存模式才走下面接通的真 gateway。clone/design 同样。
- worker（temporal activity）的 ValidateRequest 用内存 `Repository().voices`（代码种子只有 voice_sandbox），
  `hydrate_workflow_runtime_snapshot` 不从 DB 读 voices → 用户在 Web 建/导入的 voice 出片时 worker 看不到。
原则：**有 enabled 真 profile + 可用 secret 就用真 provider，否则回退 sandbox**；无 key 环境与既有测试不回退。

## 改动清单

### A. voices 业务端点接真 gateway（sqlalchemy + 内存统一）
- A1 voice preview/clone/design 的 sqlalchemy 路径（packages/media/sqlalchemy_repository.py 的 preview_voice 等
  或在 service 层统一）按 voice.provider_profile_id 路由到 `app.state.provider_gateway.invoke`，产真 artifact
  （真 minimax 音频落 ObjectStore），不再返回 sandbox:// 占位。preview 失败按 spec 2.3 错误码。
- A2 两条路径（内存/sqlalchemy）统一走同一个真 gateway 调用，消除双路径语义分叉。

### B. worker voices 从 DB hydrate
- B1 `hydrate_workflow_runtime_snapshot`（packages/production/sqlalchemy_repository.py）增加从 DB 读 voice_profiles
  灌进 repository.voices（与 provider profiles 一致，M2a 双轨消灭补漏）；ValidateRequest 能看到 DB voice。
- B2 确认 worker 的 TTS/ASR/VLM/lipsync 节点在 sqlalchemy 模式下经 DB 真 profile + gateway 调用真 provider
  （provider profiles 已从 DB 读，重点是 voice→profile 解析 + 节点实际 invoke 真 gateway 而非 sandbox 兜底）。

### C. 回归保护
- C1 既有 sandbox 默认测试不回退（无真 secret 时 preview/出片走 sandbox）。
- C2 新增测试：配 mock 真 profile+secret 时 preview/ValidateRequest 走真 gateway（mock HTTP）；DB voice 可被
  worker hydrate 看到。

## 验收门（验收官，真 key）
1. 演示库已有 4 个 MiniMax 系统音色（male-qn-qingse 等，指向 minimax.tts.prod）+ 真 secret 已灌。
2. 音色库点试听 → 出**真 MiniMax 声音**（artifact 非 sandbox://、可下载播放）。
3. 选 MiniMax 音色 + strict_timestamps 提交 run → worker ValidateRequest 通过 → 出**真声音 + 真 ASR 对齐字幕**成片。
4. 全量 + DB + Temporal 三套绿；sandbox 默认路径不回退。

## 边界
- 真 portrait + HeyGem 完整真口型片 → 仍等用户素材（本批接通 TTS/ASR/VLM，lipsync 真接通但需真 portrait 验）；M6c 冻结。
