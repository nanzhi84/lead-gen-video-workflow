import {
  caseAgentApi,
  editorHandoffApi,
  type AgentDraft,
  type AgentMemoryProposal,
  type EditorHandoffResult,
} from "../api/r6";

async function r6AgentContract(caseId: string, videoId: string) {
  const binding = await caseAgentApi.createSourceBinding(caseId, {
    source_type: "manual_note",
    source_ref: "首屏先讲可验证结果。",
    title: "R6 契约",
  });
  await caseAgentApi.deleteSourceBinding(caseId, binding.id);
  await caseAgentApi.importSource(caseId, { source_binding_id: binding.id });
  await caseAgentApi.startRun(caseId, { goal: "script_draft", source_binding_ids: [binding.id] });
  const drafts = await caseAgentApi.drafts(caseId, { limit: 30 });
  const draft: AgentDraft | undefined = drafts.items[0];
  if (draft) await caseAgentApi.adoptDraft(caseId, draft.id, { title: draft.title, publish_content: draft.script });

  const proposals = await caseAgentApi.memoryProposals(caseId, { limit: 30 });
  const proposal: AgentMemoryProposal | undefined = proposals.items[0];
  if (proposal) {
    await caseAgentApi.approveMemory(caseId, proposal.id, { reason: "R6 approve" });
    await caseAgentApi.rejectMemory(caseId, proposal.id, { reason: "R6 reject" });
  }

  await caseAgentApi.generateScript(caseId, { brief: "生成一版带案例记忆的脚本。", memory_ids: [] });
  const handoff: EditorHandoffResult = await editorHandoffApi.createEditorHandoff(videoId, { format: "zip" });
  await editorHandoffApi.createJianyingDraft(videoId, { template_id: "jianying_default" });
  handoff.package_artifact.uri satisfies string;
}

void r6AgentContract("case_demo", "finished_video_demo");
