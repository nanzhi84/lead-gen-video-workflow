import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { caseAgentApi, type AgentDraft, type AgentRun, type AgentSourceBinding } from "../../api/r6";
import { AgentDraftsPanel } from "../../components/case-agent/AgentDraftsPanel";
import { AgentMemoryPanel } from "../../components/case-agent/AgentMemoryPanel";
import { AgentRunsPanel } from "../../components/case-agent/AgentRunsPanel";
import { SourceBindingPanel } from "../../components/case-agent/SourceBindingPanel";
import { EmptyState, ErrorState, LoadingState } from "../../components/State";
import { StudioTabs } from "../../components/StudioTabs";
import { useToast } from "../../components/Toast";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { usePageVisible } from "../../hooks/usePageVisible";
import { shortId } from "../../lib/format";
import { routes } from "../../routes";

export type AdoptedAgentScriptState = {
  adoptedAgentScript?: {
    title: string;
    script: string;
    source: string;
    // Canonical adopted ScriptVersion id (E-UI): carried through StudioFlow so the
    // digital-human job submits script_version_id, not only the raw script text.
    scriptVersionId: string | null;
  };
};

export default function CaseAgentPage() {
  const { caseId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const pageVisible = usePageVisible();
  const [selectedBindingIds, setSelectedBindingIds] = useState<string[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [goal, setGoal] = useState<AgentRun["goal"]>("script_draft");
  const [pendingDelete, setPendingDelete] = useState<AgentSourceBinding | null>(null);

  const caseDetail = useQuery({
    queryKey: ["case", caseId],
    queryFn: () => api.cases.detail(caseId),
    enabled: Boolean(caseId),
  });
  const bindings = useQuery({
    queryKey: ["case-agent", caseId, "bindings"],
    queryFn: () => caseAgentApi.sourceBindings(caseId, { limit: 80 }),
    enabled: Boolean(caseId),
  });
  const runs = useQuery({
    queryKey: ["case-agent", caseId, "runs"],
    queryFn: () => caseAgentApi.runs(caseId, { limit: 30 }),
    enabled: Boolean(caseId),
    refetchInterval: pageVisible ? 10_000 : false,
  });
  const drafts = useQuery({
    queryKey: ["case-agent", caseId, "drafts"],
    queryFn: () => caseAgentApi.drafts(caseId, { limit: 30 }),
    enabled: Boolean(caseId),
  });
  const proposals = useQuery({
    queryKey: ["case-agent", caseId, "proposals"],
    queryFn: () => caseAgentApi.memoryProposals(caseId, { limit: 30 }),
    enabled: Boolean(caseId),
  });
  const selectedRun = useMemo(
    () => runs.data?.items.find((run) => run.id === selectedRunId) ?? runs.data?.items[0],
    [runs.data?.items, selectedRunId],
  );
  const runDetail = useQuery({
    queryKey: ["case-agent", caseId, "run-detail", selectedRun?.id],
    queryFn: () => caseAgentApi.runDetail(caseId, selectedRun!.id),
    enabled: Boolean(caseId && selectedRun?.id),
    refetchInterval: pageVisible ? 10_000 : false,
  });

  useEffect(() => {
    if (!selectedRunId && runs.data?.items[0]) setSelectedRunId(runs.data.items[0].id);
  }, [runs.data?.items, selectedRunId]);

  useEffect(() => {
    const availableIds = new Set(bindings.data?.items.map((item) => item.id) ?? []);
    setSelectedBindingIds((current) => current.filter((id) => availableIds.has(id)));
  }, [bindings.data?.items]);

  async function refreshAgentData() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["case-agent", caseId, "bindings"] }),
      queryClient.invalidateQueries({ queryKey: ["case-agent", caseId, "runs"] }),
      queryClient.invalidateQueries({ queryKey: ["case-agent", caseId, "drafts"] }),
      queryClient.invalidateQueries({ queryKey: ["case-agent", caseId, "proposals"] }),
    ]);
  }

  const createBinding = useMutation({
    mutationFn: (payload: Parameters<typeof caseAgentApi.createSourceBinding>[1]) =>
      caseAgentApi.createSourceBinding(caseId, payload),
    onSuccess: async (binding) => {
      toast.success("数据源绑定已创建", binding.title ?? shortId(binding.id));
      setSelectedBindingIds((current) => [...new Set([...current, binding.id])]);
      await queryClient.invalidateQueries({ queryKey: ["case-agent", caseId, "bindings"] });
    },
  });
  const deleteBinding = useMutation({
    mutationFn: (binding: AgentSourceBinding) => caseAgentApi.deleteSourceBinding(caseId, binding.id),
    onSuccess: async () => {
      toast.success("数据源绑定已删除");
      setPendingDelete(null);
      await refreshAgentData();
    },
  });
  const importSource = useMutation({
    mutationFn: (binding: AgentSourceBinding) => caseAgentApi.importSource(caseId, { source_binding_id: binding.id }),
    onSuccess: async (run) => {
      toast.success("已导入数据源", `运行 ${shortId(run.id)}`);
      setSelectedRunId(run.id);
      await refreshAgentData();
    },
  });
  const startRun = useMutation({
    mutationFn: () => caseAgentApi.startRun(caseId, { goal, source_binding_ids: selectedBindingIds }),
    onSuccess: async (run) => {
      toast.success("智能体已启动", `运行 ${shortId(run.id)}`);
      setSelectedRunId(run.id);
      await refreshAgentData();
    },
  });
  const adoptDraft = useMutation({
    mutationFn: (draft: AgentDraft) => caseAgentApi.adoptDraft(caseId, draft.id, { title: draft.title, publish_content: draft.script }),
    onSuccess: (script, draft) => {
      toast.success("草稿已采用", "已写入脚本版本，正在回填创作页");
      navigate(routes.caseStudio(caseId), {
        state: {
          adoptedAgentScript: {
            title: script.title,
            script: script.script,
            source: `案例智能体草稿 ${shortId(draft.id)}`,
            scriptVersionId: script.id,
          },
        } satisfies AdoptedAgentScriptState,
      });
    },
  });
  const approveMemory = useMutation({
    mutationFn: (proposalId: string) => caseAgentApi.approveMemory(caseId, proposalId, { reason: "前端批准入库" }),
    onSuccess: async () => {
      toast.success("记忆提案已批准");
      await queryClient.invalidateQueries({ queryKey: ["case-agent", caseId, "proposals"] });
    },
  });
  const rejectMemory = useMutation({
    mutationFn: (proposalId: string) => caseAgentApi.rejectMemory(caseId, proposalId, { reason: "前端拒绝" }),
    onSuccess: async () => {
      toast.success("记忆提案已拒绝");
      await queryClient.invalidateQueries({ queryKey: ["case-agent", caseId, "proposals"] });
    },
  });

  if (!caseId) return <EmptyState title="未选择案例" detail="请从案例中心进入工作台。" />;
  const bindingItems = bindings.data?.items ?? [];
  const runItems = runs.data?.items ?? [];

  return (
    <section className="pageStack">
      <header className="pageHeader">
        <div>
          <h1>数据 / 智能体</h1>
          <p>{caseDetail.data?.name ?? "绑定案例数据源，运行智能体，采用草稿并处理记忆提案。"}</p>
        </div>
      </header>
      <StudioTabs caseId={caseId} />
      {caseDetail.error ? <ErrorState error={caseDetail.error} /> : null}
      {bindings.error ? <ErrorState error={bindings.error} /> : null}
      {runs.error ? <ErrorState error={runs.error} /> : null}
      {drafts.error ? <ErrorState error={drafts.error} /> : null}
      {proposals.error ? <ErrorState error={proposals.error} /> : null}
      {bindings.isLoading && runs.isLoading ? <LoadingState label="加载案例智能体" /> : null}

      <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <SourceBindingPanel
          bindings={bindingItems}
          isLoading={bindings.isLoading}
          selectedIds={selectedBindingIds}
          isCreating={createBinding.isPending}
          busyBindingId={importSource.variables?.id ?? null}
          onSelect={(bindingId, selected) =>
            setSelectedBindingIds((current) =>
              selected ? [...new Set([...current, bindingId])] : current.filter((id) => id !== bindingId),
            )
          }
          onCreate={(payload) => createBinding.mutateAsync(payload)}
          onImport={(binding) => importSource.mutate(binding)}
          onDelete={setPendingDelete}
        />

        <div className="grid content-start gap-4">
          <AgentRunsPanel
            runs={runItems}
            detail={runDetail.data}
            selectedRunId={selectedRun?.id ?? null}
            selectedBindingCount={selectedBindingIds.length}
            isLoading={runs.isLoading}
            isDetailLoading={runDetail.isLoading}
            isStarting={startRun.isPending}
            goal={goal}
            onGoalChange={setGoal}
            onSelectRun={setSelectedRunId}
            onStartRun={() => startRun.mutate()}
          />
          <div className="grid items-start gap-4 lg:grid-cols-2">
            <AgentDraftsPanel
              drafts={drafts.data?.items ?? []}
              isLoading={drafts.isLoading}
              adoptingDraftId={adoptDraft.variables?.id ?? null}
              onAdopt={(draft) => adoptDraft.mutate(draft)}
            />
            <AgentMemoryPanel
              proposals={proposals.data?.items ?? []}
              isLoading={proposals.isLoading}
              busyProposalId={(approveMemory.variables ?? rejectMemory.variables) || null}
              onApprove={(proposal) => approveMemory.mutate(proposal.id)}
              onReject={(proposal) => rejectMemory.mutate(proposal.id)}
            />
          </div>
        </div>
      </div>

      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        onConfirm={() => {
          if (pendingDelete) deleteBinding.mutate(pendingDelete);
        }}
        isLoading={deleteBinding.isPending}
        type="danger"
        title="确认删除数据源绑定"
        message="删除后，后续智能体运行不会再引用该数据源。已生成的运行、草稿和记忆不会被删除。"
        consequences={["不会删除历史运行和已采用脚本", "若误删，需要重新创建绑定并导入", "正在进行的运行不会被前端强制中断"]}
        confirmText="确认删除"
      />
    </section>
  );
}
