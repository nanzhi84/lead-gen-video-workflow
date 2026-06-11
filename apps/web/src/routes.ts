export const routePatterns = {
  login: "/login",
  overview: "/",
  studio: "/studio",
  caseStudio: "/studio/:caseId",
  caseOutputs: "/studio/:caseId/outputs",
  caseRuns: "/studio/:caseId/runs",
  caseFinishedVideos: "/studio/:caseId/finished-videos",
  casePublish: "/studio/:caseId/publish",
  publishCenter: "/publish-center",
  publishCenterBatch: "/publish-center/:batchId",
  settings: "/settings",
  library: "/library/*",
  analytics: "/analytics/*",
  account: "/account/*",
  ops: "/ops/*",
} as const;

const segment = (value: string) => encodeURIComponent(value);

export const routes = {
  login: () => "/login",
  overview: () => "/",
  studio: () => "/studio",
  caseStudio: (caseId: string) => `/studio/${segment(caseId)}`,
  caseOutputs: (caseId: string) => `/studio/${segment(caseId)}/outputs`,
  caseRuns: (caseId: string) => `/studio/${segment(caseId)}/runs`,
  caseFinishedVideos: (caseId: string) => `/studio/${segment(caseId)}/finished-videos`,
  casePublish: (caseId: string) => `/studio/${segment(caseId)}/publish`,
  publishCenter: () => "/publish-center",
  publishCenterBatch: (batchId: string) => `/publish-center/${segment(batchId)}`,
  settings: (tab?: "providers" | "secrets" | "prices") => (tab ? `/settings?tab=${tab}` : "/settings"),
  library: () => "/library",
  analytics: () => "/analytics",
  account: () => "/account",
  ops: () => "/ops",
} as const;
