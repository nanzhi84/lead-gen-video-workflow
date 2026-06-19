# packages/migrations

保留这个目录级指令文件，用来防止把不同类型的迁移混在一起。当前分支不再保留旧平台资产导入助手代码；如果以后重新引入一次性迁移辅助代码，必须先更新本文件。

## 约定与要求
- `packages/migrations/` 只允许承载一次性运维迁移辅助代码，**不是** Alembic 目录。
- DB schema 迁移只能放在 `packages/core/storage/alembic/versions/`。
- 一次性迁移脚本必须默认 dry-run，真实写入必须显式 `--apply`。
- 可重跑迁移必须使用确定性的 idempotency key，不得使用随机值。
- 资产缺失、case 映射不到、外部 API 写入失败都要显式上报，不得静默吞掉。
- OSS / 外部服务凭据必须走环境变量，不得硬编码。

## 当前状态
- 旧 `legacy_assets` 迁移助手和入口脚本已移除。
- 不要在这里添加 DB schema 迁移。
