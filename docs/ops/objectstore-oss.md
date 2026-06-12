# Aliyun OSS ObjectStore

Use the S3-compatible ObjectStore backend when generated media must be reachable
by cloud providers such as DashScope ASR. For Aliyun OSS, use virtual-hosted
style addressing and the OSS region endpoint:

```bash
export CUTAGENT_OBJECTSTORE_BACKEND=s3
export CUTAGENT_OBJECTSTORE_ENDPOINT=https://oss-cn-<region>.aliyuncs.com
export CUTAGENT_OBJECTSTORE_BUCKET=<bucket>
export CUTAGENT_OBJECTSTORE_ACCESS_KEY=<access-key-id>
export CUTAGENT_OBJECTSTORE_SECRET_KEY=<access-key-secret>
export CUTAGENT_OBJECTSTORE_REGION=oss-cn-<region>
export CUTAGENT_OBJECTSTORE_ADDRESSING_STYLE=virtual
export CUTAGENT_OBJECTSTORE_MULTIPART_THRESHOLD_MB=8
export CUTAGENT_OBJECTSTORE_MULTIPART_CHUNK_MB=8
export CUTAGENT_OBJECTSTORE_MAX_CONCURRENCY=4
export CUTAGENT_OBJECTSTORE_CONNECT_TIMEOUT=10
export CUTAGENT_OBJECTSTORE_READ_TIMEOUT=120
export CUTAGENT_OBJECTSTORE_MAX_ATTEMPTS=5
```

Example for Shanghai:

```bash
export CUTAGENT_OBJECTSTORE_ENDPOINT=https://oss-cn-shanghai.aliyuncs.com
export CUTAGENT_OBJECTSTORE_REGION=oss-cn-shanghai
export CUTAGENT_OBJECTSTORE_ADDRESSING_STYLE=virtual
```

The bucket can remain private. Genesis writes artifacts to OSS and passes
presigned HTTPS URLs to ASR, so DashScope can download the TTS audio and return
real word or sentence timestamps. With this configuration, `strict_timestamps`
can use true ASR alignment for subtitles instead of estimated local timings.

MinIO remains the default local S3-compatible target. Leave
`CUTAGENT_OBJECTSTORE_ADDRESSING_STYLE` unset, or set it to `path`, for MinIO.

## Multipart transfer tuning

Remote OSS is practical for rendered media only when uploads use multipart
transfer. Portrait tracks, rendered clips, and final videos are commonly larger
than a single fast request over a distant OSS endpoint. Keep
`CUTAGENT_OBJECTSTORE_MULTIPART_THRESHOLD_MB` at or below the expected video
artifact size so boto3 switches to managed multipart upload automatically.

The default transfer settings are:

```bash
export CUTAGENT_OBJECTSTORE_MULTIPART_THRESHOLD_MB=8
export CUTAGENT_OBJECTSTORE_MULTIPART_CHUNK_MB=8
export CUTAGENT_OBJECTSTORE_MAX_CONCURRENCY=4
```

For slower links, tune request timeouts and retry attempts instead of relying
on Temporal retries around a single long object request:

```bash
export CUTAGENT_OBJECTSTORE_CONNECT_TIMEOUT=10
export CUTAGENT_OBJECTSTORE_READ_TIMEOUT=120
export CUTAGENT_OBJECTSTORE_MAX_ATTEMPTS=5
```
