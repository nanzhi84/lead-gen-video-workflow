import type { components } from "./schema";

export type PageResponse<T> = {
  items: T[];
  next_cursor?: string | null;
  total_hint?: number | null;
  request_id: string;
};

export type CaseListItem = components["schemas"]["CaseListItem"];
export type CaseDetail = components["schemas"]["CaseDetail"];
export type WorkflowRun = components["schemas"]["WorkflowRun"];
export type CreateJobResponse = components["schemas"]["CreateJobResponse"];
export type MediaAssetCard = components["schemas"]["MediaAssetCard"];
export type FinishedVideo = components["schemas"]["FinishedVideo"];
export type PublishPackage = components["schemas"]["PublishPackage"];
export type PublishBatch = components["schemas"]["PublishBatchVm"];
export type OpsDashboard = components["schemas"]["OpsDashboardVm"];

const API_BASE = "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload?.error?.message ?? `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  cases: () => request<PageResponse<CaseListItem>>("/api/cases"),
  caseDetail: (caseId: string) => request<CaseDetail>(`/api/cases/${caseId}`),
  createCase: (payload: { name: string; description?: string }) =>
    request<CaseDetail>("/api/cases", { method: "POST", body: JSON.stringify(payload) }),
  createVideoJob: (payload: {
    case_id: string;
    title: string;
    script: string;
    voice: { voice_id: string };
    portrait: { required: boolean };
    broll?: { enabled: boolean; max_inserts?: number };
    bgm?: { enabled: boolean };
    subtitles?: { enabled: boolean };
  }) => request<CreateJobResponse>("/api/jobs/digital-human-video", { method: "POST", body: JSON.stringify(payload) }),
  runReport: (runId: string) => request<{ public_report: { status: string; degradations: string[]; warnings: string[]; summary: string } }>(`/api/runs/${runId}/report`),
  assets: () => request<PageResponse<MediaAssetCard>>("/api/media/assets"),
  finishedVideos: (caseId: string) => request<PageResponse<FinishedVideo>>(`/api/cases/${caseId}/finished-videos`),
  publishPackages: () => request<PageResponse<PublishPackage>>("/api/publish/packages"),
  publishBatches: () => request<PageResponse<PublishBatch>>("/api/publish/batches"),
  createPublishPackage: (payload: { source_finished_video_id: string; title: string; description: string }) =>
    request<PublishPackage>("/api/publish/packages", { method: "POST", body: JSON.stringify(payload) }),
  createPublishBatch: (payload: { publish_package_ids: string[]; platform_targets: string[] }) =>
    request<PublishBatch>("/api/publish/batches", { method: "POST", body: JSON.stringify(payload) }),
  submitPublishBatch: (batchId: string) =>
    request<PublishBatch>(`/api/publish/batches/${batchId}/submit`, { method: "POST", body: JSON.stringify({ dry_run: false }) }),
  opsDashboard: () => request<OpsDashboard>("/api/ops/dashboard"),
  providerProfiles: () => request<PageResponse<{ id: string; display_name: string; capability: string; enabled: boolean }>>("/api/providers/profiles"),
  providerBalances: () => request<{ items: Array<{ provider_id: string; status: string; quota_remaining?: number | null }> }>("/api/providers/balances"),
};
