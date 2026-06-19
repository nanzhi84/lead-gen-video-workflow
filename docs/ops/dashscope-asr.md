# DashScope ASR Real Run Prerequisite

DashScope Paraformer ASR runs as an async cloud task. The task downloads the
input audio from the `file_urls` value submitted by Cutagent, so production ASR
requires a public, DashScope-reachable audio URL.

Use public OSS or another public HTTPS object endpoint for real ASR alignment.
Local MinIO URLs such as `127.0.0.1:9000` are not reachable from DashScope and
will make the ASR task fail.

`strict_timestamps=true` depends on this prerequisite because strict subtitle
alignment must come from the ASR provider. With `strict_timestamps=false`,
Cutagent may soft-degrade to estimated narration timestamps and still render a
local video when ASR is unavailable.

M6L durable fixes also seed a production-ready creative intent prompt and keep
non-strict narration alignment on the estimated path after an ASR failure.
