# M7 架构加固验收记录（红/黄风险修复，离线+live）

负责：Opus 子代理（7 个并行 worktree 实现）/ Claude（架构 + 验收集成）
来源：架构评估报告 `docs/audit/architecture-assessment-2026-06-13.md` 的红/黄行动项。
合并：`3041826`（6 个低风险）+ `acc8002`（repo-scoping，单独可回退）。验收日期：2026-06-13。

## 修了什么（7 项）

| 修复 | 风险 | 文件 |
|---|---|---|
| **repo-scoping**：消除进程级共享 in-memory Repository，每个 Temporal activity 新建 per-activity Repository（hydrate→run→persist→discard），杜绝跨 run 串台 + 无界泄漏 | 🔴 最高 | temporal_adapter / digital_human / worker/main |
| **ephemeral fail-fast**：temporal runtime 下 ephemeral 落 local 则启动拒绝（防多 worker 静默失败） | 🔴 | object_store_env |
| **provider limiter**：按 ProviderProfile.concurrency_key 的进程内信号量限并发（背压 vs 厂商配额） | 🔴 | provider_limiter + gateway |
| **outbox SKIP LOCKED**：派发用 `FOR UPDATE SKIP LOCKED`（Postgres）认领，多副本不重复推；sqlite 回退 | 🟡 | events |
| **artifacts 索引**：`idx_artifacts_run` + `(run_id,kind)` + alembic 0004（最热 hydration 查询原本无索引） | 🟡 | database + 0004 |
| **media streaming**：S3 按 path 流式上下传（upload_file/download_file + sha256_file），不再把分钟级视频全量进内存；Local 后端不变 | 🟡 | object_store / tiered / assets |
| **contract 修复**：OutboxEvent.dedupe_key 重复声明（required 后又 Optional）→ 恢复 required str | 🟡 | contracts |

## 验收（离线）

- 7 个 patch 由 7 个隔离 worktree Opus 子代理各自实现 + 自测，**全部 disjoint 文件**，干净 apply。
- 全量套件 **exit 0**（绿）；ruff F401/F821 全清；openapi/schema.d.ts 重新生成**零漂移**；前端 tsc exit 0。
- 每项各带隔离单测（sqlite/mock，不碰共享 DB）。

## 验收（live，真 Temporal + Postgres + OSS）— 关键

- migration 0004 应用于 demo DB：`idx_artifacts_run` + `idx_artifacts_run_kind` 建成。
- worker + API 重启于新代码：**ephemeral fail-fast 正确未触发**（demo ephemeral=s3/MinIO）；worker ready，repo-scoping 启动干净。
- **真 Temporal run 端到端成功**（run_1da78c3b4241，非 strict，真 MiniMax TTS + 真 DashScope ASR + ffmpeg render）：**15 节点 succeeded + 1 skipped（LipSync）**，全 16 节点跑通。
  - 这是 repo-scoping 的决定性验证：每个节点在独立 activity 里用**全新 per-activity Repository** 正确 hydrate 了前序节点的 DB 状态——若 scoping 坏了会在第 2 节点就失败。7 项修复同时在 live 路径跑通。

## 结论

架构评估的红/黄风险全部修复，离线三套绿 + live 真 Temporal run 端到端成功。repo-scoping（#1 风险，8/12 评审独立指出）已 live 证伪「跨 run 串台」隐患被消除。系统在多 worker/多副本下的正确性闸门补齐。

## 后续（评估报告里 🟢 later，未做）
- 连接池 env 化；拆 3 个 god-file（多日重构，待 parity/CI 安全网后做）。
- 把 SQL+Temporal 集成测试纳入默认 CI（报告 #1 建议的安全网——本次靠 live demo 验证，CI 自动化是后续）。
- provider limiter 目前是进程内；集群级配额需共享限流器（Redis 令牌桶）。
