# M6Q + M6R 验收记录（Wave 1，真 live）

负责：Codex（执行）/ Claude（架构 + 验收）
合并：`058b941` Merge M6Q、`af6da8d` Merge M6R（均 `--no-ff` 入 main，无冲突）
验收日期：2026-06-13

补做 parity 审计 5 个真缺口的第一波：①Provider 真实余额轮询、③平台用量/API 监控（M6Q）；⑤Prompt 四组集中管理（M6R）。

## 离线验证（合并后 main，组合验证）

- 后端全量：`.venv/bin/python -m pytest` → **215 passed / 23 skipped**（M6Q+M6R 合并后一起跑，0 失败；M6Q 单独 212/9、M6R 单独 203/9）。skipped 多出的是 DB/Temporal 集成项，验收官在 live 段单独覆盖。
- 前端：`cd apps/web && npx tsc --noEmit` → exit 0；`npm run build` → ✓ built（1732 modules）。
- OpenAPI/schema.d.ts 同步（contract test `test_openapi_matrix` 绿）。

## Live 验证（demo 环境：OSS durable + 本机 MinIO ephemeral 分层存储，Temporal worker）

环境：r6 runtime clone fast-forward 到 main；`alembic upgrade head` 应用迁移 `0002_provider_balance_snapshots`；`bootstrap_sqlalchemy_storage()` 幂等补种（新增 38 行 = 19 模板 + 19 版本，无新 binding）；API 8021 + worker 重启于合并代码。

### M6Q 余额（门 #1）— 真 key

`POST /api/providers/balances/refresh`（operator，经 SecretStore 取真 key）：

| profile | 状态 | 余额 | 备注 |
|---|---|---|---|
| **runninghub.heygem** | **ok** | **¥2.60 / 68,080 coins** | 真实拉取 RunningHub 账户 |
| dashscope.asr/llm/vlm | unsupported | — | DashScope 需阿里云 BSS 账户级查询（诚实标注，不伪造） |
| minimax.tts | unsupported | — | MiniMax 无余额 API |
| sandbox ×3 | unconfigured | — | 无 secret，标未配置不报错 |

- `GET /api/providers/balances` 刷新前 `{items:[], status:"pending"}`（mock 已替换为读快照）；刷新后 8 条快照落 `provider_balance_snapshots`，带 `checked_at`。
- 前端「余额&配额」tab：表格真数显示，状态徽标 i18n（正常/不支持/未配置），「立即刷新」按钮，无假数。

### M6Q 用量监控（门 #2）— 真 invocation 聚合

`GET /api/ops/provider-usage-metrics`（按 provider × capability × model 聚合既往真 run）：

| provider | capability · model | calls | success_rate | cost |
|---|---|---|---|---|
| dashscope.llm | llm.chat · qwen-plus | 11 | 100% | ¥0.003262 |
| minimax.tts | tts.speech · speech-02-hd | 9 | 100% | ¥0.063 |
| dashscope.asr | asr.transcribe · paraformer-v2 | 8 | 75% | ¥0.029025 |
| runninghub.heygem | lipsync.video · heygem-webapp | 3 | 66.7% | — |

汇总：31 calls / 90.3% / ¥0.095287。成功率非 100% 的是真实重试（ASR/lipsync 早期失败），非编造。前端「API 用量监控」tab：SVG 条形图 + 汇总 + 明细，空态友好。

### M6R Prompt 四组（门 #1）— Playwright

`/ops/prompts` 页：
- 四组 tab：**脚本工作台·10 / 视频分析 VL·3 / 发布封面·2 / 剪辑 Agent·4**（共 19，purpose 前缀分组）。
- 模板全部标「未绑定」（19 个新 prompt 无伪造 binding；原 3 个 binding 不动）。
- 变量 chip：点击插入 `{var}`，hints 来自 seed 元数据（如 semantic pack 17 个变量全列）。
- 「恢复默认」按钮 = rollback 到 v1。
- brace 安全：seed 单测 `test_prompt_group_seeds_create_four_groups_with_brace_safe_content` 对全部 19 个 prompt 实跑 `str.format(**hints)` 不抛（M6L 教训已内化）。

截图：`m6r-prompt-groups-script.png`、`m6q-balance-tab.png`、`m6q-usage-tab.png`。

## 结论

M6Q、M6R 两个真缺口补做完成，离线三套绿 + live 真数验证通过。Wave 1 收尾，进入 Wave 2（M6S 对标提取 + M6T broll 预览/选材账本）。
