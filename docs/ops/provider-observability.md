# Provider Observability

M6Q exposes provider balance snapshots through `GET /api/providers/balances` and refreshes them through `POST /api/providers/balances/refresh`.

The API process does not start a resident balance poller. Operators can refresh on demand from the UI, or an external cron/worker can import and call `apps.api.services.providers.refresh_all_balances(request)` inside an API application context. That function queries configured provider profiles, writes `provider_balance_snapshots`, and returns the latest `ProviderBalanceReport`.

Provider profiles without a readable `secret_ref` are recorded as `unconfigured`. Providers without a balance API, such as MiniMax, are recorded as `unsupported`. Provider HTTP failures are saved as `error` with sanitized detail text.
