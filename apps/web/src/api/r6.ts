import { createIdempotencyKey, fetchJson } from "./client";
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

const enc = encodeURIComponent;

export type AgentSourceBinding = components["schemas"]["CaseAgentSourceBinding"];
export type AgentRun = components["schemas"]["CaseAgentRun"];
export type AgentRunDetail = components["schemas"]["CaseAgentRunDetail"];
export type AgentDraft = components["schemas"]["ScriptDraft"];
export type AgentMemoryProposal = components["schemas"]["MemoryProposal"];
export type EditorHandoffResult = components["schemas"]["EditorHandoffPackageArtifact"];
export type JianyingDraftResult = components["schemas"]["JianyingDraftPackageArtifact"];

export const caseAgentApi = {
  sourceBindings: (
    caseId: string,
    query: QueryParams<operations["source_bindings_api_cases__case_id__agent_source_bindings_get"]> = {},
  ) =>
    fetchJson<JsonResponse<operations["source_bindings_api_cases__case_id__agent_source_bindings_get"]>>(
      `/api/cases/${enc(caseId)}/agent/source-bindings`,
      { query },
    ),
  createSourceBinding: (
    caseId: string,
    payload: JsonRequest<operations["create_source_binding_api_cases__case_id__agent_source_bindings_post"]>,
  ) =>
    fetchJson<JsonResponse<operations["create_source_binding_api_cases__case_id__agent_source_bindings_post"]>>(
      `/api/cases/${enc(caseId)}/agent/source-bindings`,
      { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("agent_source") },
    ),
  deleteSourceBinding: (caseId: string, bindingId: string) =>
    fetchJson<JsonResponse<operations["delete_source_binding_api_cases__case_id__agent_source_bindings__binding_id__delete"]>>(
      `/api/cases/${enc(caseId)}/agent/source-bindings/${enc(bindingId)}`,
      { method: "DELETE", idempotencyKey: createIdempotencyKey("agent_source_delete") },
    ),
  importSource: (
    caseId: string,
    payload: JsonRequest<operations["import_case_source_api_cases__case_id__agent_import_source_post"]>,
  ) =>
    fetchJson<JsonResponse<operations["import_case_source_api_cases__case_id__agent_import_source_post"]>>(
      `/api/cases/${enc(caseId)}/agent/import-source`,
      { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("agent_import") },
    ),
  startRun: (
    caseId: string,
    payload: JsonRequest<operations["start_case_agent_run_api_cases__case_id__agent_runs_post"]>,
  ) =>
    fetchJson<JsonResponse<operations["start_case_agent_run_api_cases__case_id__agent_runs_post"]>>(
      `/api/cases/${enc(caseId)}/agent/runs`,
      { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("agent_run") },
    ),
  runs: (caseId: string, query: QueryParams<operations["case_agent_runs_api_cases__case_id__agent_runs_get"]> = {}) =>
    fetchJson<JsonResponse<operations["case_agent_runs_api_cases__case_id__agent_runs_get"]>>(
      `/api/cases/${enc(caseId)}/agent/runs`,
      { query },
    ),
  runDetail: (caseId: string, runId: string) =>
    fetchJson<JsonResponse<operations["case_agent_run_detail_api_cases__case_id__agent_runs__run_id__get"]>>(
      `/api/cases/${enc(caseId)}/agent/runs/${enc(runId)}`,
    ),
  drafts: (caseId: string, query: QueryParams<operations["script_drafts_api_cases__case_id__agent_drafts_get"]> = {}) =>
    fetchJson<JsonResponse<operations["script_drafts_api_cases__case_id__agent_drafts_get"]>>(
      `/api/cases/${enc(caseId)}/agent/drafts`,
      { query },
    ),
  adoptDraft: (
    caseId: string,
    draftId: string,
    payload: JsonRequest<operations["adopt_script_draft_api_cases__case_id__agent_drafts__draft_id__adopt_post"]>,
  ) =>
    fetchJson<JsonResponse<operations["adopt_script_draft_api_cases__case_id__agent_drafts__draft_id__adopt_post"]>>(
      `/api/cases/${enc(caseId)}/agent/drafts/${enc(draftId)}/adopt`,
      { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("agent_draft_adopt") },
    ),
  memoryProposals: (
    caseId: string,
    query: QueryParams<operations["memory_proposals_api_cases__case_id__agent_memory_proposals_get"]> = {},
  ) =>
    fetchJson<JsonResponse<operations["memory_proposals_api_cases__case_id__agent_memory_proposals_get"]>>(
      `/api/cases/${enc(caseId)}/agent/memory-proposals`,
      { query },
    ),
  approveMemory: (
    caseId: string,
    memoryId: string,
    payload: JsonRequest<operations["approve_memory_api_cases__case_id__memory__memory_id__approve_post"]>,
  ) =>
    fetchJson<JsonResponse<operations["approve_memory_api_cases__case_id__memory__memory_id__approve_post"]>>(
      `/api/cases/${enc(caseId)}/memory/${enc(memoryId)}/approve`,
      { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("memory_approve") },
    ),
  rejectMemory: (
    caseId: string,
    memoryId: string,
    payload: JsonRequest<operations["reject_memory_api_cases__case_id__memory__memory_id__reject_post"]>,
  ) =>
    fetchJson<JsonResponse<operations["reject_memory_api_cases__case_id__memory__memory_id__reject_post"]>>(
      `/api/cases/${enc(caseId)}/memory/${enc(memoryId)}/reject`,
      { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("memory_reject") },
    ),
  generateScript: (
    caseId: string,
    payload: JsonRequest<operations["generate_script_with_memory_api_cases__case_id__scripts_generate_with_memory_post"]>,
  ) =>
    fetchJson<JsonResponse<operations["generate_script_with_memory_api_cases__case_id__scripts_generate_with_memory_post"]>>(
      `/api/cases/${enc(caseId)}/scripts/generate-with-memory`,
      { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("script_memory") },
    ),
};

export const editorHandoffApi = {
  createEditorHandoff: (
    videoId: string,
    payload: JsonRequest<operations["editor_handoff_api_finished_videos__id__editor_handoff_post"]>,
  ) =>
    fetchJson<JsonResponse<operations["editor_handoff_api_finished_videos__id__editor_handoff_post"]>>(
      `/api/finished-videos/${enc(videoId)}/editor-handoff`,
      { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("editor_handoff") },
    ),
  createJianyingDraft: (
    videoId: string,
    payload: JsonRequest<operations["jianying_draft_api_finished_videos__id__jianying_draft_post"]>,
  ) =>
    fetchJson<JsonResponse<operations["jianying_draft_api_finished_videos__id__jianying_draft_post"]>>(
      `/api/finished-videos/${enc(videoId)}/jianying-draft`,
      { method: "POST", body: payload, idempotencyKey: createIdempotencyKey("jianying_draft") },
    ),
};
