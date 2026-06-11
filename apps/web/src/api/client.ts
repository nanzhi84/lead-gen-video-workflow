import type { components, operations } from "./schema";

type JsonRequest<Operation> = Operation extends {
  requestBody: { content: { "application/json": infer Body } };
}
  ? Body
  : never;

type JsonResponse<Operation> = Operation extends {
  responses: {
    200: { content: { "application/json": infer Body } };
  };
}
  ? Body
  : Operation extends {
        responses: {
          201: { content: { "application/json": infer Body } };
        };
      }
    ? Body
    : Operation extends {
          responses: {
            202: { content: { "application/json": infer Body } };
          };
        }
      ? Body
      : never;

type QueryParams<Operation> = Operation extends {
  parameters: { query?: infer Query };
}
  ? Query
  : never;

export type ApiError = Error & {
  code?: components["schemas"]["ErrorCode"] | string;
  requestId?: string;
  status: number;
  details?: unknown;
};

type FetchOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  idempotencyKey?: string;
};

const JSON_TYPE = "application/json";

export function createIdempotencyKey(prefix = "request") {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}_${crypto.randomUUID()}`;
  }
  return `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function buildUrl(path: string, query?: FetchOptions["query"]) {
  const search = new URLSearchParams();
  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  });
  const suffix = search.toString();
  return suffix ? `${path}?${suffix}` : path;
}

function readErrorMessage(code: string | undefined, fallback: string) {
  if (code === "auth.invalid_credentials") {
    return "邮箱或密码不正确";
  }
  if (code === "auth.unauthorized") {
    return "登录已失效，请重新登录";
  }
  if (code === "auth.forbidden") {
    return "当前账号没有权限执行此操作";
  }
  return fallback;
}

function getObject(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

async function parseError(response: Response): Promise<ApiError> {
  const payload = getObject(await response.json().catch(() => undefined));
  const rawError = getObject(payload?.error);
  const code = typeof rawError?.code === "string" ? rawError.code : undefined;
  const message =
    typeof rawError?.message === "string"
      ? readErrorMessage(code, rawError.message)
      : readErrorMessage(code, `请求失败（${response.status}）`);
  const requestId =
    (typeof rawError?.request_id === "string" && rawError.request_id) ||
    (typeof payload?.request_id === "string" && payload.request_id) ||
    response.headers.get("X-Request-Id") ||
    undefined;
  const error = new Error(message) as ApiError;
  error.status = response.status;
  error.code = code;
  error.requestId = requestId;
  error.details = rawError?.details ?? payload;
  return error;
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof Error && "status" in error;
}

export async function fetchJson<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", JSON_TYPE);
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    headers.set("Content-Type", JSON_TYPE);
  }
  if (options.idempotencyKey) {
    headers.set("Idempotency-Key", options.idempotencyKey);
  }

  const response = await fetch(buildUrl(path, options.query), {
    ...options,
    credentials: "include",
    headers,
    body:
      options.body === undefined
        ? undefined
        : options.body instanceof FormData
          ? options.body
          : JSON.stringify(options.body),
  });

  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("cutagent:unauthorized"));
    }
    throw await parseError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

const enc = encodeURIComponent;

export const api = {
  auth: {
    login: (payload: JsonRequest<operations["login_api_auth_login_post"]>) =>
      fetchJson<JsonResponse<operations["login_api_auth_login_post"]>>("/api/auth/login", {
        method: "POST",
        body: payload,
      }),
    session: () =>
      fetchJson<JsonResponse<operations["session_api_auth_session_get"]>>("/api/auth/session"),
    logout: () =>
      fetchJson<JsonResponse<operations["logout_api_auth_logout_post"]>>("/api/auth/logout", {
        method: "POST",
        idempotencyKey: createIdempotencyKey("logout"),
      }),
  },
  cases: {
    list: (query: QueryParams<operations["list_cases_api_cases_get"]> = {}) =>
      fetchJson<JsonResponse<operations["list_cases_api_cases_get"]>>("/api/cases", { query }),
    create: (payload: JsonRequest<operations["create_case_api_cases_post"]>) =>
      fetchJson<JsonResponse<operations["create_case_api_cases_post"]>>("/api/cases", {
        method: "POST",
        body: payload,
        idempotencyKey: createIdempotencyKey("case"),
      }),
    detail: (caseId: string) =>
      fetchJson<JsonResponse<operations["case_detail_api_cases__case_id__get"]>>(`/api/cases/${enc(caseId)}`),
    runs: (caseId: string, query: QueryParams<operations["case_run_cards_api_cases__case_id__runs_get"]> = {}) =>
      fetchJson<JsonResponse<operations["case_run_cards_api_cases__case_id__runs_get"]>>(
        `/api/cases/${enc(caseId)}/runs`,
        { query },
      ),
  },
  voices: {
    list: (query: QueryParams<operations["list_voices_api_voices_get"]> = {}) =>
      fetchJson<JsonResponse<operations["list_voices_api_voices_get"]>>("/api/voices", { query }),
    clone: (payload: JsonRequest<operations["clone_voice_api_voices_clone_post"]>) =>
      fetchJson<JsonResponse<operations["clone_voice_api_voices_clone_post"]>>("/api/voices/clone", {
        method: "POST",
        body: payload,
        idempotencyKey: createIdempotencyKey("voice_clone"),
      }),
    design: (payload: JsonRequest<operations["design_voice_api_voices_design_post"]>) =>
      fetchJson<JsonResponse<operations["design_voice_api_voices_design_post"]>>("/api/voices/design", {
        method: "POST",
        body: payload,
        idempotencyKey: createIdempotencyKey("voice_design"),
      }),
    preview: (voiceId: string, payload: JsonRequest<operations["voice_preview_api_voices__voice_id__preview_post"]>) =>
      fetchJson<JsonResponse<operations["voice_preview_api_voices__voice_id__preview_post"]>>(
        `/api/voices/${enc(voiceId)}/preview`,
        { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("voice_preview") },
      ),
    patch: (voiceId: string, payload: JsonRequest<operations["patch_voice_api_voices__voice_id__patch"]>) =>
      fetchJson<JsonResponse<operations["patch_voice_api_voices__voice_id__patch"]>>(`/api/voices/${enc(voiceId)}`, {
        method: "PATCH",
        body: payload,
        idempotencyKey: createIdempotencyKey("voice_patch"),
      }),
    delete: (voiceId: string) =>
      fetchJson<JsonResponse<operations["delete_voice_api_voices__voice_id__delete"]>>(`/api/voices/${enc(voiceId)}`, {
        method: "DELETE",
        idempotencyKey: createIdempotencyKey("voice_delete"),
      }),
  },
  uploads: {
    prepare: (payload: JsonRequest<operations["prepare_upload_api_uploads_prepare_post"]>) =>
      fetchJson<JsonResponse<operations["prepare_upload_api_uploads_prepare_post"]>>("/api/uploads/prepare", {
        method: "POST",
        body: payload,
        idempotencyKey: createIdempotencyKey("upload_prepare"),
      }),
    uploadFile: (uploadSessionId: string, file: File) => {
      const body = new FormData();
      body.set("file", file);
      return fetchJson<JsonResponse<operations["upload_file_api_uploads__upload_session_id__file_put"]>>(
        `/api/uploads/${enc(uploadSessionId)}/file`,
        { method: "PUT", body },
      );
    },
    complete: (payload: JsonRequest<operations["complete_upload_api_uploads_complete_post"]>) =>
      fetchJson<JsonResponse<operations["complete_upload_api_uploads_complete_post"]>>("/api/uploads/complete", {
        method: "POST",
        body: payload,
        idempotencyKey: createIdempotencyKey("upload_complete"),
      }),
    cancel: (uploadSessionId: string) =>
      fetchJson<JsonResponse<operations["cancel_upload_api_uploads__upload_session_id__cancel_post"]>>(
        `/api/uploads/${enc(uploadSessionId)}/cancel`,
        { method: "POST", idempotencyKey: createIdempotencyKey("upload_cancel") },
      ),
    get: (uploadSessionId: string) =>
      fetchJson<JsonResponse<operations["get_upload_api_uploads__upload_session_id__get"]>>(
        `/api/uploads/${enc(uploadSessionId)}`,
      ),
  },
  mediaAssets: {
    list: (query: QueryParams<operations["list_media_assets_api_media_assets_get"]> = {}) =>
      fetchJson<JsonResponse<operations["list_media_assets_api_media_assets_get"]>>("/api/media/assets", { query }),
    create: (payload: JsonRequest<operations["create_media_asset_api_media_assets_post"]>) =>
      fetchJson<JsonResponse<operations["create_media_asset_api_media_assets_post"]>>("/api/media/assets", {
        method: "POST",
        body: payload,
        idempotencyKey: createIdempotencyKey("media_asset"),
      }),
    detail: (assetId: string) =>
      fetchJson<JsonResponse<operations["media_asset_detail_api_media_assets__asset_id__get"]>>(
        `/api/media/assets/${enc(assetId)}`,
      ),
    previewUrl: (assetId: string) =>
      fetchJson<JsonResponse<operations["media_asset_preview_api_media_assets__asset_id__preview_url_get"]>>(
        `/api/media/assets/${enc(assetId)}/preview-url`,
      ),
  },
  annotations: {
    get: (assetId: string) =>
      fetchJson<JsonResponse<operations["get_annotation_api_annotations__asset_id__get"]>>(
        `/api/annotations/${enc(assetId)}`,
      ),
    patch: (assetId: string, payload: JsonRequest<operations["patch_annotation_api_annotations__asset_id__patch"]>) =>
      fetchJson<JsonResponse<operations["patch_annotation_api_annotations__asset_id__patch"]>>(
        `/api/annotations/${enc(assetId)}`,
        { method: "PATCH", body: payload, idempotencyKey: createIdempotencyKey("annotation_patch") },
      ),
    rerun: (assetId: string, payload: JsonRequest<operations["rerun_annotation_api_annotations__asset_id__rerun_post"]>) =>
      fetchJson<JsonResponse<operations["rerun_annotation_api_annotations__asset_id__rerun_post"]>>(
        `/api/annotations/${enc(assetId)}/rerun`,
        { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("annotation_rerun") },
      ),
  },
  jobs: {
    createDigitalHumanVideo: (
      payload: JsonRequest<operations["create_digital_human_job_api_jobs_digital_human_video_post"]>,
      idempotencyKey = createIdempotencyKey("video_job"),
    ) =>
      fetchJson<JsonResponse<operations["create_digital_human_job_api_jobs_digital_human_video_post"]>>(
        "/api/jobs/digital-human-video",
        { method: "POST", body: payload, idempotencyKey },
      ),
  },
  runs: {
    detail: (runId: string) =>
      fetchJson<JsonResponse<operations["run_detail_api_runs__run_id__get"]>>(`/api/runs/${enc(runId)}`),
    cancel: (runId: string, payload: JsonRequest<operations["cancel_run_api_runs__run_id__cancel_post"]>) =>
      fetchJson<JsonResponse<operations["cancel_run_api_runs__run_id__cancel_post"]>>(
        `/api/runs/${enc(runId)}/cancel`,
        { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("cancel_run") },
      ),
    retry: (runId: string, payload: JsonRequest<operations["retry_run_api_runs__run_id__retry_post"]>) =>
      fetchJson<JsonResponse<operations["retry_run_api_runs__run_id__retry_post"]>>(
        `/api/runs/${enc(runId)}/retry`,
        { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("retry_run") },
      ),
    resume: (runId: string, payload: JsonRequest<operations["resume_run_api_runs__run_id__resume_post"]>) =>
      fetchJson<JsonResponse<operations["resume_run_api_runs__run_id__resume_post"]>>(
        `/api/runs/${enc(runId)}/resume`,
        { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("resume_run") },
      ),
    events: (runId: string) =>
      fetchJson<JsonResponse<operations["run_events_api_runs__run_id__events_get"]>>(`/api/runs/${enc(runId)}/events`),
  },
  finishedVideos: {
    list: (caseId: string) =>
      fetchJson<JsonResponse<operations["case_finished_videos_api_cases__case_id__finished_videos_get"]>>(
        `/api/cases/${enc(caseId)}/finished-videos`,
      ),
    previewUrl: (id: string) =>
      fetchJson<JsonResponse<operations["finished_video_preview_api_finished_videos__id__preview_url_get"]>>(
        `/api/finished-videos/${enc(id)}/preview-url`,
      ),
    downloadUrl: (id: string) =>
      fetchJson<JsonResponse<operations["finished_video_download_api_finished_videos__id__download_get"]>>(
        `/api/finished-videos/${enc(id)}/download`,
      ),
    delete: (id: string) =>
      fetchJson<JsonResponse<operations["delete_finished_video_api_finished_videos__id__delete"]>>(
        `/api/finished-videos/${enc(id)}`,
        { method: "DELETE", idempotencyKey: createIdempotencyKey("delete_video") },
      ),
  },
  publishing: {
    packages: (query: QueryParams<operations["publish_packages_api_publish_packages_get"]> = {}) =>
      fetchJson<JsonResponse<operations["publish_packages_api_publish_packages_get"]>>("/api/publish/packages", {
        query,
      }),
    createPackage: (payload: JsonRequest<operations["create_publish_package_api_publish_packages_post"]>) =>
      fetchJson<JsonResponse<operations["create_publish_package_api_publish_packages_post"]>>("/api/publish/packages", {
        method: "POST",
        body: payload,
        idempotencyKey: createIdempotencyKey("publish_package"),
      }),
    patchPackage: (
      packageId: string,
      payload: JsonRequest<operations["patch_publish_package_api_publish_packages__package_id__patch"]>,
    ) =>
      fetchJson<JsonResponse<operations["patch_publish_package_api_publish_packages__package_id__patch"]>>(
        `/api/publish/packages/${enc(packageId)}`,
        { method: "PATCH", body: payload, idempotencyKey: createIdempotencyKey("publish_package_patch") },
      ),
    batches: (query: QueryParams<operations["publish_batches_api_publish_batches_get"]> = {}) =>
      fetchJson<JsonResponse<operations["publish_batches_api_publish_batches_get"]>>("/api/publish/batches", {
        query,
      }),
    createBatch: (payload: JsonRequest<operations["create_publish_batch_api_publish_batches_post"]>) =>
      fetchJson<JsonResponse<operations["create_publish_batch_api_publish_batches_post"]>>("/api/publish/batches", {
        method: "POST",
        body: payload,
        idempotencyKey: createIdempotencyKey("publish_batch"),
      }),
    batch: (batchId: string) =>
      fetchJson<JsonResponse<operations["publish_batch_detail_api_publish_batches__batch_id__get"]>>(
        `/api/publish/batches/${enc(batchId)}`,
      ),
    attempts: (
      batchId: string,
      query: QueryParams<operations["publish_batch_attempts_api_publish_batches__batch_id__attempts_get"]> = {},
    ) =>
      fetchJson<JsonResponse<operations["publish_batch_attempts_api_publish_batches__batch_id__attempts_get"]>>(
        `/api/publish/batches/${enc(batchId)}/attempts`,
        { query },
      ),
    deleteBatch: (batchId: string) =>
      fetchJson<JsonResponse<operations["delete_publish_batch_api_publish_batches__batch_id__delete"]>>(
        `/api/publish/batches/${enc(batchId)}`,
        { method: "DELETE", idempotencyKey: createIdempotencyKey("publish_batch_delete") },
      ),
    submitBatch: (
      batchId: string,
      payload: JsonRequest<operations["submit_publish_batch_api_publish_batches__batch_id__submit_post"]>,
    ) =>
      fetchJson<JsonResponse<operations["submit_publish_batch_api_publish_batches__batch_id__submit_post"]>>(
        `/api/publish/batches/${enc(batchId)}/submit`,
        { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("publish_submit") },
      ),
    retryItem: (batchId: string, itemId: string) =>
      fetchJson<JsonResponse<operations["retry_publish_item_api_publish_batches__batch_id__items__item_id__retry_publish_post"]>>(
        `/api/publish/batches/${enc(batchId)}/items/${enc(itemId)}/retry-publish`,
        { method: "POST", idempotencyKey: createIdempotencyKey("publish_retry") },
      ),
    patchItem: (itemId: string, payload: JsonRequest<operations["patch_publish_item_api_publish_items__item_id__patch"]>) =>
      fetchJson<JsonResponse<operations["patch_publish_item_api_publish_items__item_id__patch"]>>(
        `/api/publish/items/${enc(itemId)}`,
        { method: "PATCH", body: payload, idempotencyKey: createIdempotencyKey("publish_item_patch") },
      ),
    deleteItem: (itemId: string) =>
      fetchJson<JsonResponse<operations["delete_publish_item_api_publish_items__item_id__delete"]>>(
        `/api/publish/items/${enc(itemId)}`,
        { method: "DELETE", idempotencyKey: createIdempotencyKey("publish_item_delete") },
      ),
    attempt: (attemptId: string) =>
      fetchJson<JsonResponse<operations["publish_attempt_api_publish_attempts__attempt_id__get"]>>(
        `/api/publish/attempts/${enc(attemptId)}`,
      ),
  },
  providers: {
    profiles: (query: QueryParams<operations["provider_profiles_api_providers_profiles_get"]> = {}) =>
      fetchJson<JsonResponse<operations["provider_profiles_api_providers_profiles_get"]>>("/api/providers/profiles", {
        query,
      }),
    createProfile: (payload: JsonRequest<operations["create_provider_profile_api_providers_profiles_post"]>) =>
      fetchJson<JsonResponse<operations["create_provider_profile_api_providers_profiles_post"]>>(
        "/api/providers/profiles",
        { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("provider_profile") },
      ),
    patchProfile: (
      profileId: string,
      payload: JsonRequest<operations["patch_provider_profile_api_providers_profiles__profile_id__patch"]>,
    ) =>
      fetchJson<JsonResponse<operations["patch_provider_profile_api_providers_profiles__profile_id__patch"]>>(
        `/api/providers/profiles/${enc(profileId)}`,
        { method: "PATCH", body: payload, idempotencyKey: createIdempotencyKey("provider_profile") },
      ),
    testProfile: (
      profileId: string,
      payload: JsonRequest<operations["test_provider_profile_api_providers_profiles__profile_id__test_post"]>,
    ) =>
      fetchJson<JsonResponse<operations["test_provider_profile_api_providers_profiles__profile_id__test_post"]>>(
        `/api/providers/profiles/${enc(profileId)}/test`,
        { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("provider_test") },
      ),
    capabilities: () =>
      fetchJson<JsonResponse<operations["provider_capabilities_api_providers_capabilities_get"]>>(
        "/api/providers/capabilities",
      ),
    priceCatalogs: (query: QueryParams<operations["price_catalogs_api_providers_price_catalogs_get"]> = {}) =>
      fetchJson<JsonResponse<operations["price_catalogs_api_providers_price_catalogs_get"]>>(
        "/api/providers/price-catalogs",
        { query },
      ),
    priceCatalogItems: (
      catalogId: string,
      query: QueryParams<operations["price_catalog_items_api_providers_price_catalogs__catalog_id__items_get"]> = {},
    ) =>
      fetchJson<JsonResponse<operations["price_catalog_items_api_providers_price_catalogs__catalog_id__items_get"]>>(
        `/api/providers/price-catalogs/${enc(catalogId)}/items`,
        { query },
      ),
    upsertPriceCatalog: (payload: JsonRequest<operations["upsert_price_catalog_api_providers_price_catalogs_post"]>) =>
      fetchJson<JsonResponse<operations["upsert_price_catalog_api_providers_price_catalogs_post"]>>(
        "/api/providers/price-catalogs",
        { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("price_catalog") },
      ),
    approvePriceCatalog: (
      catalogId: string,
      payload: JsonRequest<operations["approve_price_catalog_api_providers_price_catalogs__catalog_id__approve_post"]>,
    ) =>
      fetchJson<JsonResponse<operations["approve_price_catalog_api_providers_price_catalogs__catalog_id__approve_post"]>>(
        `/api/providers/price-catalogs/${enc(catalogId)}/approve`,
        { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("price_approve") },
      ),
    publishPriceCatalog: (
      catalogId: string,
      payload: JsonRequest<operations["publish_price_catalog_api_providers_price_catalogs__catalog_id__publish_post"]>,
    ) =>
      fetchJson<JsonResponse<operations["publish_price_catalog_api_providers_price_catalogs__catalog_id__publish_post"]>>(
        `/api/providers/price-catalogs/${enc(catalogId)}/publish`,
        { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("price_publish") },
      ),
  },
  secrets: {
    list: () => fetchJson<JsonResponse<operations["list_secrets_api_secrets_get"]>>("/api/secrets"),
    create: (payload: JsonRequest<operations["create_secret_api_secrets_post"]>) =>
      fetchJson<JsonResponse<operations["create_secret_api_secrets_post"]>>("/api/secrets", {
        method: "POST",
        body: payload,
        idempotencyKey: createIdempotencyKey("secret"),
      }),
    rotate: (secretId: string, payload: JsonRequest<operations["rotate_secret_api_secrets__secret_id__rotate_post"]>) =>
      fetchJson<JsonResponse<operations["rotate_secret_api_secrets__secret_id__rotate_post"]>>(
        `/api/secrets/${enc(secretId)}/rotate`,
        { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("secret_rotate") },
      ),
    disable: (secretId: string, payload: JsonRequest<operations["disable_secret_api_secrets__secret_id__disable_patch"]>) =>
      fetchJson<JsonResponse<operations["disable_secret_api_secrets__secret_id__disable_patch"]>>(
        `/api/secrets/${enc(secretId)}/disable`,
        { method: "PATCH", body: payload, idempotencyKey: createIdempotencyKey("secret_disable") },
      ),
  },
} as const;

export type AuthUser = components["schemas"]["AuthUser"];
export type CaseListItem = components["schemas"]["CaseListItem"];
export type CaseDetail = components["schemas"]["CaseDetail"];
export type WorkflowRun = components["schemas"]["WorkflowRun"];
export type NodeRun = components["schemas"]["NodeRun"];
export type RunCard = components["schemas"]["RunCard"];
export type RunDetailResponse = components["schemas"]["RunDetailResponse"];
export type VoiceProfile = components["schemas"]["VoiceProfile"];
export type UploadKind = components["schemas"]["UploadKind"];
export type UploadSession = components["schemas"]["UploadSession"];
export type CompleteUploadResponse = components["schemas"]["CompleteUploadResponse"];
export type MediaAssetCard = components["schemas"]["MediaAssetCard"];
export type MediaAssetRecord = components["schemas"]["MediaAssetRecord"];
export type AnnotationEditorVm = components["schemas"]["AnnotationEditorVm"];
export type FinishedVideo = components["schemas"]["FinishedVideo"];
export type PublishAttempt = components["schemas"]["PublishAttempt"];
export type PublishAttemptDetail = components["schemas"]["PublishAttemptDetail"];
export type PublishBatch = components["schemas"]["PublishBatchVm"];
export type PublishBatchItem = components["schemas"]["PublishBatchItemVm"];
export type PublishPackage = components["schemas"]["PublishPackage"];
export type ProviderProfile = components["schemas"]["ProviderProfile"];
export type SecretPreview = components["schemas"]["SecretPreview"];
export type ProviderPriceCatalog = components["schemas"]["ProviderPriceCatalog"];
export type ProviderPriceItem = components["schemas"]["ProviderPriceItem-Output"];
