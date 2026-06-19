# M6k 施工简报：根治磁盘累积（seed/测试产物幂等 + 临时化 + 保留期 GC）

负责：Codex（执行）/ Claude（架构 + 验收）
分支：`feat/m6k-disk-rootcause`
依据：用户反馈——临时数据撑爆 C 盘（WSL .vhdx），最大元凶 `.data/objectstore/seed-media` 累积约 40G+。
Spec：第 5 章（Artifact 内容寻址 sha256）、第 17 章（不把临时态当真相）。

## 根因（验收官已定位，勿改诊断结论）

1. **ObjectStore 键非幂等**：`packages/core/storage/object_store.py` 的 `prepare_upload(filename, purpose)`
   两个实现（Local/S3）都用 `key = f"{purpose}/{uuid4().hex}/{safe_name}"` —— **每次调用都生成全新随机目录**，
   即使内容完全相同也会再写一份。
2. **seed 媒体每次构造流水线都重存**：`packages/production/pipeline/digital_human.py`
   的 `_ensure_seed_media_assets()` 在 `DigitalHumanPipeline.__init__` 每次都跑；
   - in-memory repo 每个新进程都从无 `source_artifact_id` 的 seed 资产起步 → 首次构造就重存；
   - sqlalchemy 路径里 `self.repository.media_assets[asset_id] = asset.model_copy(...)`（line ~255）
     只改了**内存快照**，没回写 DB → 每次 hydrate 出来仍无 `source_artifact_id` → **每次构造都重存 3 段 seed**。
   叠加根因 1 的 uuid 键 → `objectstore/seed-media/<uuid>/...` 无界增长（40G 来源）。
3. **运行产物 + 测试产物无保留期**：`generated-video/generated-audio/subtitles/covers` 每次 run 都新写、永不清；
   测试套件直接写仓库内 `.data/objectstore`（默认 `CUTAGENT_LOCAL_OBJECTSTORE_PATH=.data/objectstore`），
   每跑一次测试就把仓库 `.data` 撑大一点。

## 改动清单

### A. 内容寻址幂等存储（杀掉根因 1+2 的磁盘影响）

- A1 `ObjectStore.prepare_upload` 加可选 keyword 参数 `content_key: str | None = None`（基类签名 + Local + S3 三处）：
  - 给了 `content_key` → `key = f"{purpose}/{content_key}/{safe_name}"`（确定性，可被覆盖写）；
  - 不给 → 维持现状 `uuid4().hex`（**向后兼容，运行产物路径不变**）。
- A2 `packages/media/assets.py` 的 `store_file(object_store, path, *, purpose, addressed: bool = False)`：
  当 `addressed=True` 时**先读字节算 `sha256`**，把前 N 位（用全 64 位即可）作为 `content_key` 传入 →
  同内容永远落到同一个 key，重复 `store_file` 即覆盖写、不再新增目录。返回的 `StoredObject.sha256` 不变。
- A3 `digital_human.py` 的 seed 媒体存储改为 `store_file(get_object_store(), path, purpose="seed-media", addressed=True)`
  （line ~235）。**这一条单独就根治 seed 累积**：无论 source_artifact_id 是否持久化，重复 bootstrap 只会覆盖同一组 key。
- A4 **不要**给运行产物（generated-video/audio/subtitles/covers，line 925/1863/2006/2067/2069/2132）加 `addressed`：
  它们每次 run 内容不同，内容寻址无去重价值且会干扰保留期 GC——保持 uuid 键。

### B. 测试产物临时化（杀掉根因 3 的测试部分）

- B1 `tests/conftest.py` **顶部**（在 `from tests.fixtures.media import ...` 等会触发 app/object_store 导入的语句**之前**）：
  用 `tempfile.mkdtemp(prefix="cutagent-test-objstore-")` 建一个会话级临时目录，
  `os.environ.setdefault("CUTAGENT_LOCAL_OBJECTSTORE_PATH", <该临时目录>)`，
  并 `atexit.register(shutil.rmtree, <该目录>, ignore_errors=True)` 在进程退出时清掉。
  注意：`object_store.py` 的 `_OBJECT_STORE` 是模块级单例、在导入时按 env 构建，所以**必须在任何导入它的语句之前 set env**
  （root conftest 模块体先于其它测试模块执行，放最顶即可）。
- B2 加一条单测断言：测试期 `get_object_store().root`（Local）位于系统临时目录之下、不在仓库 `.data/objectstore`。

### C. 开发态保留期 GC 工具（兜住根因 3 的 dev demo 部分）

- C1 新增 `scripts/gc_objectstore.py`（命令行）：扫描 LocalObjectStore root（或 S3 的 `objectstore-cache`）下
  `generated-video/generated-audio/subtitles/covers` 前缀，按文件 mtime 删除早于 `--max-age-hours`（默认 24）的对象目录；
  **默认 dry-run**（只打印将删什么 + 累计释放字节），`--apply` 才真删；`seed-media` 前缀默认**跳过**（幂等的、体积小）。
  路径从 `CUTAGENT_LOCAL_OBJECTSTORE_PATH` 读，可 `--root` 覆盖。删除前打印每条，结束打印总释放量。
- C2 简短 ops 文档：`docs/ops/objectstore-gc.md`（怎么跑、定时建议），README 运维段落加一行指引。
- C3（标注为 follow-up，不在本批做）：基于 DB artifact 引用的 orphan GC（删除无任何 artifact 引用的对象）需连库，留待后续。

### D. （可选，低优先）seed source_artifact_id 持久化

- D1 sqlalchemy 路径让 seed 资产的 `source_artifact_id` 真正回写 DB，避免每次 hydrate 都重跑 ffmpeg+store（**省 CPU，不省磁盘**，磁盘已由 A3 解决）。
  **若改动面大则跳过**并在简报尾注明，不要为此扩大 blast radius。

## 边界（Out of scope）

- 运行产物的内容寻址去重、orphan GC（连库）、S3 端 lifecycle policy 配置：本批不做。
- 不动前端、不动 provider、不动业务逻辑；只动存储键 + conftest + 新增 GC 脚本。

## Verification（sandbox 内，Codex 自验）

- 全量 pytest（基线约 130 单测 + provider/contract）不回退；新单测（A2 幂等键、B2 临时根、C1 GC 干跑/实删）全绿。
- 所有 pytest 调用包 `timeout -k 5 600`（sandbox TestClient 线程死锁防护）。
- `prepare_upload(content_key=...)` Local+S3 确定性键单测；`store_file(addressed=True)` 同内容两次 → 同 uri、对象数不增。
- 构造 `DigitalHumanPipeline` 两次（用 in-memory repo），断言 `seed-media` 下唯一内容目录数恒为 3（不随构造次数线性增长）。

## 验收门（验收官执行）

1. 重复 bootstrap N 次 → `objectstore/seed-media` 目录数 == 唯一内容数（3），非 N×3。
2. 跑全量测试 → 仓库 `.data/objectstore` 不增长（写入落系统临时目录）。
3. `scripts/gc_objectstore.py` 干跑列出陈旧 generated-* 产物、`--apply` 真删并打印释放量。
4. 全量 + DB + Temporal 三套绿。

---

## 验收记录（2026-06-12，验收官：Claude）

**判定：通过并合入**（merge f1b0b3a）。

Codex 落地 A/B/C，D 跳过（source_artifact_id 持久化属纯 CPU 优化，磁盘已由 A3 解决，避免扩大范围）。
提交曾被 Codex sandbox 只读 `.git` 阻断，由验收官在沙箱外 commit（a2ea39c）。

验收官独立证据：
- **全量单测独立复跑：178 passed, 23 skipped**（基线 ~130 增长无回退；object_store backend / assets / digital_human seed / gc 四组新测齐全）。
- **实证幂等不累积**（live LocalObjectStore，非 mock）：同内容 5 次 `store_file(addressed=True, purpose="seed-media")` → `seed-media/` 仅 1 目录、1 唯一 uri；对照 `addressed=False, purpose="generated-video"` 5 次 → 5 目录 5 uri（运行产物按预期保持唯一）；`StoredObject.sha256` 与源文件一致。
- 改面核对：`prepare_upload(content_key=)` 仅基类+Local+S3 三处加 keyword（向后兼容）；`digital_human.py` **仅** seed-media 那一处 store_file 加 `addressed=True`，其余 6 处运行产物调用未动；conftest 顶部在 app 导入前 `setdefault` 临时 objectstore root + atexit 清理；GC 默认 dry-run、只扫 generated-*/subtitles/covers、跳过 seed-media。

DB/Temporal 集成：M6k 不触及 DB schema 与 workflow 代码，且本机 DB 集成会 DROP SCHEMA 抹掉演示库（含步骤3 需要的 4 个 MiniMax 音色 + group_id 配置）。裁决：DB+Temporal 三套绿并入**步骤3 重建演示**时一并跑（届时本就要重建+重新 seed），避免双重抹库。
