export const routePatterns = {
  login: "/login",
  studio: "/studio",
  caseStudio: "/studio/:caseId",
  caseRuns: "/studio/:caseId/runs",
  caseFinishedVideos: "/studio/:caseId/finished-videos",
  casePublish: "/studio/:caseId/publish",
  settings: "/settings",
  library: "/library/*",
  ops: "/ops/*",
} as const;

const segment = (value: string) => encodeURIComponent(value);

export const routes = {
  login: () => "/login",
  studio: () => "/studio",
  caseStudio: (caseId: string) => `/studio/${segment(caseId)}`,
  caseRuns: (caseId: string) => `/studio/${segment(caseId)}/runs`,
  caseFinishedVideos: (caseId: string) => `/studio/${segment(caseId)}/finished-videos`,
  casePublish: (caseId: string) => `/studio/${segment(caseId)}/publish`,
  settings: (tab?: "providers" | "secrets" | "prices") => (tab ? `/settings?tab=${tab}` : "/settings"),
  library: () => "/library",
  ops: () => "/ops",
} as const;
