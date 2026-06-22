# 素材库音色分厂商多音色管理 + 火山豆包语音接入 · 设计方案

- 日期：2026-06-22
- 分支：`worktree-voice-multi-vendor`（基于 main `0646403`）
- 状态：设计待评审（火山接口已用真实凭据端到端实测坐实，无未知数）

---

## 1. 背景与目标

音色（`VoiceProfile`）当前隐性绑定单一厂商 MiniMax。目标：把素材库音色改造成**分厂商多音色管理 + 分厂商试听**，并接入**火山引擎豆包语音（声音复刻）**作为并列的新厂商。

核心用户诉求：MiniMax 与火山都能「在平台复刻音色 → 试听 → 进成片调用」，音色按厂商分 Tab 管理、按厂商试听。

## 2. 范围

**In：**
- 新增火山豆包语音 provider（合成 + 声音复刻 + 自动同步已复刻音色）。
- MiniMax 与火山**并存**（双厂商）。
- **平台内上传复刻：双厂商都做，走统一上传 UI + 状态机**。MiniMax 现有 `_clone` 端到端代码完整（前端上传参考音频→`/files/upload`→`/voice_clone`→试听），本次是**确认其配置可用**（强依赖 profile 的 `group_id` + active secret）而非重写；火山新增 `mega_tts` 数据面复刻。
- 音色数据模型加 `vendor`（厂商归属）+ `status`（复刻状态机）两字段。
- 前端音色库**厂商一级 Tab**（全部 / MiniMax / 火山豆包）+ 分厂商试听。
- 火山凭据全自动：AK/SK + AppID（一次性配置）→ 自动签发 `x-api-key` + 自动同步复刻音色。

**Out（明确不做）：**
- **文字设计音色 design**：MiniMax 与火山都不做，下线 MiniMax 现有 design 链路（保留 `designed` 枚举值仅兼容历史数据）。
- **火山预置音色**：不 seed 火山预置音色枚举表（`ListSpeakers` 能力保留为将来扩展点，本次不用）。
- 不引入 Temporal worker 做复刻轮询（用前端轮询）。

## 3. 现状（关键：系统已"半厂商无关"）

- **分发层已厂商无关**：`ProviderGateway` 按 `profile.provider_id` 字典查表分发（`provider_gateway.py:269 plugins[profile.provider_id]`），多厂商天然共存，**加火山零改 gateway 骨架**。
- **TTS 唯一插件** = `MiniMaxTTSProvider`（`provider_id="minimax.tts"`，`capability="tts.speech"`），一插件四职：`speech/clone/design/voice_list`，靠 `input["operation"]` 二次分发。
- **试听 = 实时同步合成**（`/api/voices/{id}/preview`，非预置样音，非 job 化），已支持透传 `provider_profile_id` → **分厂商试听后端天然支持**。
- **`VoiceProfile`**（`contracts/media.py:362`）字段极简：`display_name / source(builtin|cloned|designed) / provider_profile_id / preview_artifact_id / enabled`，**无 vendor 字段**；表 `voice_profiles`（`database.py:338`）DDL 在 ORM（无独立 CREATE 迁移，0001 用 `create_all`）。
- **核心坑**：`minimax.py` 兼管 同步/克隆/设计/合成 四职，**裸换厂商会拖掉同步/克隆**——所以走「并存」而非「替换」。

## 4. 架构总览

```
                         capability = "tts.speech"
   ┌───────────────── ProviderGateway (按 provider_id 分发，零改) ─────────────────┐
   │                                                                              │
   ▼                                                                              ▼
MiniMaxTTSProvider (minimax.tts)                          VolcengineTTSProvider (volcengine.tts)  ← 新增
  · speech / clone / voice_list                             · speech  (openspeech, x-api-key)
  · (design 下线)                                            · clone   (声音复刻 2.0 数据面)
                                                            · voice_list (= 管理面 ListMegaTTSTrainStatus, AK/SK)
                                                            · sign_key  (= 管理面 CreateAPIKey/ListAPIKeys, AK/SK)
```

- 火山一个插件内同样按 `operation` 分发，但跨**两套鉴权**：数据面（合成/复刻训练，`x-api-key`）+ 管理面（同步/签发，`AK/SK` V4 签名）。
- 音色按 `voice.provider_profile_id → profile.provider_id` 归属厂商；`vendor` 字段冗余该归属，供 UI 分组与后端过滤。

## 5. 数据模型变更

`VoiceProfile`（契约）+ `VoiceProfileRow`（ORM）各加两列：

| 字段 | 类型 | 含义 / 默认 |
|---|---|---|
| `vendor` | `str`（`minimax` / `volcengine`）| 厂商归属。同步/克隆/创建时按所用 profile 的 `provider_id` 前缀回填。历史行按 `provider_profile_id` 反推，反推不到记 `unknown` |
| `status` | `Literal["ready","training","failed"]` | 复刻状态机。MiniMax 同步秒回→直接 `ready`；火山复刻异步→`training`→轮询转 `ready`/`failed`。历史行默认 `ready` |

- **Contract-first**：改 `media.py` → `python scripts/export_openapi.py && (cd apps/web && npm run generate:api)` 重生成 `openapi.json` + `schema.d.ts`（CI 校验漂移）。
- **迁移**：新增幂等 ALTER 迁移（编号接当前实际 head——本地 `0011`、mac mini prod 已到 `0020`，实现时确认并续号），参照 `0006` 的 inspect-then-add 写法，给已有行补默认值。
- **source 兼容**：保留 `designed` 枚举值仅兼容历史，不再新建 designed 音色。
- **双后端**：内存 `repository.py` 的 `voice_sandbox` 种子同步补 `vendor`/`status` 默认值。

## 6. 火山接入：实测坐实的接口契约

> 全部用用户主账户 AK/SK（`AccessKeyId AKLT… / SecretAccessKey`）+ AppID `9635790622` + 已有 `x-api-key` 真实跑通，下列均为实测结果。

### 6.1 凭据三件套

| 凭据 | 用途 | 存放 |
|---|---|---|
| **AK/SK**（主账户级）| 管理面 OpenAPI（同步音色 + 签发/列 key），V4 HMAC 签名 | SecretStore（独立信封）|
| **AppID**（`9635790622`）| 管理面 body 必填参数 | `ProviderProfile.default_options`（一次性配置，非密）|
| **x-api-key**（`f660e4fc-…`）| 数据面合成/复刻调用 header | SecretStore（可由 AK/SK 自动签发，见 6.4）|

- 三者互相独立，互不通用。AK/SK **不能**直接调数据面合成；`x-api-key` **不能**调管理面。
- 签名**复用** `packages/ops/balance/providers/volcengine.py` 的 `_signed_headers()`（V4 HMAC-SHA256，纯 stdlib），扩展支持 POST：`method=POST`、canonical query=`Action=<X>&Version=<Y>`、`payload_hash=sha256(json_body)`、signed headers 仍 `host;x-content-sha256;x-date`、补 `Content-Type: application/json`。已用 `QueryBalanceAcct` 验证签名实现正确。

### 6.2 数据面合成（声音复刻 / 预置通用）

- `POST https://openspeech.bytedance.com/api/v1/tts`
- Header：`x-api-key: <key>`、`Content-Type: application/json`
- Body：
  ```json
  {"app":{"cluster":"volcano_icl"},
   "user":{"uid":"<任意标识>"},
   "audio":{"voice_type":"S_UDXV2pG62","encoding":"mp3","speed_ratio":1.0},
   "request":{"reqid":"<uuid>","text":"...","operation":"query"}}
  ```
  - `cluster`：复刻音色 = `volcano_icl`；预置大模型音色 = `volcano_tts`。
  - `voice_type`：复刻 = `SpeakerID`（`S_…`）；预置 = `VoiceType`（如 `zh_female_vv_uranus_bigtts`）。
  - `operation: "query"` = HTTP 一次性合成（同步）。
- 返回：`{code:3000, message:"Success", data:"<base64 mp3>", addition:{duration,first_pkg}}` — **同步返回 base64 音频**，与现有 preview 同步契约兼容。`code != 3000` 为失败。

### 6.3 管理面 OpenAPI（AK/SK V4 签名）

- host `open.volcengineapi.com`、region `cn-north-1`、Service `speech_saas_prod`、POST、JSON body。

| Action | Version | Body | 返回关键字段 |
|---|---|---|---|
| `ListMegaTTSTrainStatus` | `2025-05-21` | `{"AppID":"9635790622"}` | `Result.Statuses[]`：`SpeakerID`(S_…)、`Alias`(用户音色名)、`State`(Success/…)、`InstanceStatus`(active)、`IsActivatable`、`DemoAudio`(官方试听URL,带签名会过期)、`ResourceID`(seed-icl-2.0)、`AvailableTrainingTimes`、`ModelTypeDetails[]`{`ModelType`,`IclSpeakerId`,`ResourceID`,`DemoAudio`} |
| `ListAPIKeys` | `2025-05-20` | `{"AppID":"9635790622"}` | `Result.APIKeys[]`：`ID`(int)、`Name`、`APIKey`(**明文**,可随时列回)、`Disable`、`CreateTime` |
| `CreateAPIKey` | `2025-05-20` | `{"AppID":...,"Name":"<名称>","ProjectName":<可选>}` | 建 key（响应体未建模）；建完调 `ListAPIKeys` 按 `Name` 捞明文 `APIKey` |
| `ServiceStatus` | `2025-05-20` | 需额外 `BlueprintID`/`ResourceID` | 服务开通状态（非核心，按需）|

### 6.4 自动签发 x-api-key（路径 B）

1. 启动/配置时：`ListAPIKeys(AppID)` → 若已有未禁用 key，直接取明文存 SecretStore（复用，免重复建）。
2. 若无：`CreateAPIKey(AppID, Name="cutagent-tts-<ts>")` → 紧接 `ListAPIKeys` 按 Name 捞明文 → 存 SecretStore。
3. 数据面合成从 SecretStore 取该 `x-api-key`。
4. 轮换：禁用旧 key + 重签发，更新 SecretStore。

## 7. 火山 provider 适配器设计

新建 `packages/ai/providers/volcengine_tts.py`，`provider_id="volcengine.tts"`、`capability="tts.speech"`，鸭子类型 `invoke_with_context`，按 `operation` 分发：

- `speech`：6.2 合成（复刻音色默认 `cluster=volcano_icl`）。
- `clone`（平台内复刻，用户核心诉求）：火山声音复刻 2.0 数据面（`mega_tts/audio/upload` 上传训练音频 → `mega_tts/status` 轮询 → 产出 `SpeakerID`）。与已坐实的合成同属 `openspeech.bytedance.com` 数据面（同源 `x-api-key` 体系，风险低），但上传/训练接口的精确字段**实现期实测补全**（本设计已坐实合成/同步/签发三链路）。
- `voice_list`：调管理面 `ListMegaTTSTrainStatus`（AK/SK），映射成统一 `[{voice_id=SpeakerID, display_name=Alias, source=cloned, status, preview_url=DemoAudio}]`。
- 配套：`netpolicy.py` `DEFAULT_ALLOWED_HOSTS` 加 `openspeech.bytedance.com` + `open.volcengineapi.com`（后者 billing 已加）；`provider_seed.py` 加 `volcengine.tts.prod` profile（`default_options` 放 `appid/cluster/data_base_url/openapi_*`）+ 按字符 price catalog/item。

## 8. 复刻状态机

```
clone 提交
  ├─ MiniMax：同步返回 voice_id → 落库 status=ready
  └─ 火山：上传训练 → 落库 status=training → 前端轮询 GET /api/voices/{id}
            后端调 ListMegaTTSTrainStatus 查 State：
              Success → status=ready（回填 SpeakerID 为 voice_id）
              Failed  → status=failed（带错误）
```

- 前端对 `training` 音色显示「训练中」徽标 + 禁用试听，轮询转 `ready` 解锁；`failed` 可重试。

## 9. 音色同步设计（双厂商）

`sync_voices` 改为**按厂商遍历**所有 enabled `tts.speech` profile 分别同步（现状 `_select_tts_profile_for_sync` 只取第一个 = 多厂商下行为不确定，必须改）：

- MiniMax：`voice_list`（`get_voice` 拉账户克隆音色）。
- 火山：`voice_list`（管理面 `ListMegaTTSTrainStatus(AppID)` 拉复刻音色）。
- upsert 时带 `vendor` + `status` + `preview_url(DemoAudio)`，主键沿用厂商原生 id（MiniMax voice_id / 火山 SpeakerID，命名空间天然不冲突，不加跨厂商唯一约束）。
- `SyncVoicesRequest.provider_profile_id` 已支持「按厂商同步」。

## 10. 试听设计

- **优先用同步时拿到的 `DemoAudio`**（火山官方试听样音 URL）做即时试听——零合成成本。URL 带签名会过期，过期/缺失时**回退实时合成**（现有 preview 链路，火山走 `volcano_icl`+SpeakerID）。
- MiniMax 仍走实时合成试听（无现成样音 URL）。
- preview 已透传 `provider_profile_id`，分厂商试听天然支持。

## 11. API / 服务层变更

- `clone` 必须带 `provider_profile_id`（选厂商）；服务层回填 `vendor`。
- **按厂商能力优雅降级**：`services/voices.py` 对「厂商不支持某 operation」显式报 `provider_unsupported_option`，不再假设选中 profile 一定能跑该 operation。
- `GET /api/voices` 加 `vendor` 过滤参数（契约改动，随重生成）。
- **删除** `/api/voices/design` 端点 + `design_voice` service + `DesignVoiceRequest` 契约 + `minimax.py._design`。
- preview 基本不改（已支持分厂商 + DemoAudio 优化在服务层）。

## 12. 前端 UI

- **厂商一级 Tab**：音色库顶部「全部 / MiniMax / 火山豆包」，Tab 内保留「系统/克隆」筛选（数据来自 `vendor` 字段或 `api.providers.profiles({capability:"tts.speech"})`）。
- **克隆弹窗选厂商**：裸文本「Provider 配置 ID」→ 按厂商分组的下拉。
- **VoiceCard** 厂商徽标 + `training`/`failed` 状态徽标（training 禁用试听）。
- **试听面板** 音色下拉按厂商 `optgroup` 分组。
- **删除** design 入口（DesignVoiceModal + 设计音色按钮 + libraryModel designed 入口）。
- `realData.ts` sandbox 过滤保留，给「未指定厂商（vendor=unknown）」音色兜底分组。

## 13. design 下线清理清单

前端 `DesignVoiceModal`/设计按钮、后端 `/api/voices/design` 端点 + `design_voice` + `DesignVoiceRequest`、`minimax.py._design`、`libraryModel` designed 标签入口——全部清理；仅留 `source="designed"` 枚举值兼容历史数据。

## 14. 错误处理与降级

- 厂商不支持 operation → 显式 `provider_unsupported_option`（不静默）。
- 火山复刻训练失败 → `status=failed` + 错误信息，可重试。
- 火山合成 `code != 3000` → 显式上报（分级 degradation）。
- 计费缺价目 → 现有 `cost.unpriced` 告警；火山按字符配 `ProviderPriceItem`（`unit=input_token=len(text)`）避免记 0。
- host 白名单：生产开启 `enforce_host_allowlist` 时火山两个 host 必须在 `DEFAULT_ALLOWED_HOSTS`。
- 试听 `DemoAudio` 过期/失败 → 回退实时合成。

## 15. 测试策略

- 火山适配器单测：mock 合成（base64 解码/`code` 分支）、mock 管理面 `ListMegaTTSTrainStatus`/`ListAPIKeys` 响应、V4 签名头构造、自动签发流程。
- 复刻状态机单测（training→ready/failed 转移）。
- 分厂商 list（vendor 过滤）/ preview（按 profile 分流）集成测试。
- design 下线回归（端点 404、UI 入口消失、历史 designed 音色仍可列/试听）。
- 契约漂移校验（CI 门禁）。
- 本地跑测试用空 `CUTAGENT_SECRET_STORE_DIR` 复刻 CI（避免本地 `.data/secrets` 真实密钥污染）。

## 16. 风险与前置依赖

| 项 | 说明 / 处置 |
|---|---|
| **账户余额 0** | 实测 `AvailableBalance=0`。复刻有免费额度（3 音色各剩 14 次训练 + 20000 字符试听），但量产合成前需充值，否则合成可能余额不足失败 |
| **x-api-key 已暴露** | 当前 key 明文出现在对话；落地前在控制台/`CreateAPIKey` 轮换一把 |
| **AK/SK 权限** | 主账户 AK/SK 实测可调 billing + speech_saas_prod；生产建议改用带最小策略的子用户 AK/SK |
| **DemoAudio 过期** | 试听 URL 带 `x-expires` 签名，过期回退实时合成 |
| **prod 库迁移** | mac mini prod 已到 `0020`，新迁移续号并幂等 ALTER `voice_profiles` |
| **计费价目** | 火山按字符（约 6.5→4.9 元/万字），配 price_item |
| **火山复刻数据面接口** | 火山平台内复刻（mega_tts 上传/训练）数据面字段实现期实测补全（合成/同步/签发已坐实，同源 x-api-key）|
| **MiniMax 复刻现状** | `_clone` 代码完整但依赖 profile 配 `group_id` + active secret；用户反馈"没有"大概率是未配通，本次确认端到端可用而非重写 |

## 17. 实测证据附录

- `QueryBalanceAcct` → 200，AccountID `2108685169`，`AvailableBalance=0`（签名实现验证）。
- 合成预置 `zh_female_vv_uranus_bigtts`（`volcano_tts`）→ 200 / `code=3000` / 40KB mp3。
- 合成复刻 `S_UDXV2pG62`「无忧快喷」（`volcano_icl`）→ 200 / `code=3000` / 89KB mp3 / 4.4s。
- `ListMegaTTSTrainStatus(AppID=9635790622, 2025-05-21)` → 200，拉出 `S_UDXV2pG62`(无忧快喷)/`S_TDXV2pG62`(三只喜鹊)/(龙哥轮毂) 含 SpeakerID/Alias/State=Success/DemoAudio/ResourceID=seed-icl-2.0。
- `ListAPIKeys(AppID, 2025-05-20)` → 200，明文 `APIKey=f660e4fc-…`（ID 197901，未禁用）。
