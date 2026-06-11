import type { ApiError } from "../api/client";
import { api, createIdempotencyKey } from "../api/client";
import { routes } from "../routes";

async function assertM6aApiSurface() {
  const login = await api.auth.login({ email: "admin@example.com", password: "password" });
  const session = await api.auth.session();
  const cases = await api.cases.list({ search: "demo" });
  const runs = await api.cases.runs("case_123");

  login.user.role satisfies "admin" | "operator" | "viewer";
  session.user.email satisfies string;
  cases.items[0]?.active_memory_count satisfies number | undefined;
  runs.items[0]?.runId satisfies string | undefined;
  runs.items[0]?.canRetry satisfies boolean | undefined;
  createIdempotencyKey("case") satisfies string;
  routes.caseStudio("case_123") satisfies string;
  routes.caseRuns("case_123") satisfies string;
}

function assertErrorShape(error: ApiError) {
  error.message satisfies string;
  error.requestId satisfies string | undefined;
  error.code satisfies string | undefined;
}

void assertM6aApiSurface;
void assertErrorShape;
