// Probes the LOCKED Case profile + edit contract shapes against the regenerated schema.
// Runs at integration via `tsc -b` after the single OpenAPI regen; it exercises the new
// CaseListItem counts/industry, the Case profile fields, the PATCH client, and the
// E-UI script_version_id threading. No runtime side effects.
import {
  api,
  type CaseDetail,
  type CaseListItem,
  type CreateCaseRequest,
  type PatchCaseRequest,
} from "../api/client";
import {
  buildCreatePayload,
  buildPatchPayload,
  joinList,
  parseList,
} from "../components/modals/CaseModal";
import type { AdoptedAgentScriptState } from "../pages/studio/CaseAgentPage";
import type { FormState } from "../components/studio-create/studioCreateModel";

async function assertCaseEditContract(caseId: string) {
  // R6: industry filter param on the list query.
  const listed = await api.cases.list({ search: null, industry: "education", limit: 100 });
  const item: CaseListItem | undefined = listed.items[0];
  if (item) {
    // R6: per-case counts + industry on the list item (defaulted in contract).
    item.material_count satisfies number;
    item.script_count satisfies number;
    item.voice_count satisfies number;
    item.quality_count satisfies number;
    item.industry satisfies string | null | undefined;
  }

  // R1: create with the new profile fields.
  const createPayload: CreateCaseRequest = {
    name: "契约案例",
    description: "描述",
    industry: "education",
    product: "产品",
    target_audience: "受众",
    key_selling_points: ["卖点一", "卖点二"],
    ip_persona: "稳重专家",
    brand_voice: "亲切专业",
    strategy_tags: ["增长", "复购"],
    brand_keywords: ["关键词"],
    competitor_names: ["竞品A"],
  };
  const created: CaseDetail = await api.cases.create(createPayload);

  // R1 / B-UI: PATCH the profile fields.
  const patchPayload: PatchCaseRequest = {
    name: "改名",
    industry: "saas",
    key_selling_points: ["新卖点"],
    ip_persona: null,
    brand_voice: null,
    strategy_tags: [],
    brand_keywords: [],
    competitor_names: [],
    status: "active",
  };
  const patched: CaseDetail = await api.cases.patch(created.id, patchPayload);

  // CaseDetail exposes the profile fields back to the UI.
  patched.key_selling_points satisfies string[];
  patched.ip_persona satisfies string | null | undefined;
  patched.brand_voice satisfies string | null | undefined;
  patched.strategy_tags satisfies string[];
  patched.brand_keywords satisfies string[];
  patched.competitor_names satisfies string[];

  // Modal helpers round-trip list fields and produce typed payloads.
  joinList(patched.strategy_tags) satisfies string;
  parseList("a\nb, c") satisfies string[];
  buildCreatePayload satisfies (form: never) => CreateCaseRequest;
  buildPatchPayload satisfies (form: never) => PatchCaseRequest;
  void caseId;
}

// E-UI: script_version_id flows draft.adopt -> AdoptedAgentScriptState -> FormState -> job.
async function assertScriptVersionThreading(caseId: string, draftId: string) {
  const state: AdoptedAgentScriptState = {
    adoptedAgentScript: {
      title: "标题",
      script: "正文",
      source: "案例智能体草稿",
      scriptVersionId: "sv_123",
    },
  };
  state.adoptedAgentScript?.scriptVersionId satisfies string | null | undefined;

  const formScriptVersionId: FormState["scriptVersionId"] = "sv_123";
  formScriptVersionId satisfies string | null;

  const created = await api.jobs.createDigitalHumanVideo({
    schema_version: "digital_human_video_request.v1",
    case_id: caseId,
    script: "正文",
    title: null,
    publish_content: "",
    script_version_id: "sv_123",
    workflow_template_id: "digital_human_v2",
  });
  created.initial_run satisfies unknown;
  void draftId;
}

void assertCaseEditContract;
void assertScriptVersionThreading;
