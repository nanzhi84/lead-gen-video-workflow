import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Play, RotateCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api, type ApiError, type RunCard } from "../../api/client";
import { EmptyState, ErrorState, LoadingState } from "../../components/State";
import { StatusPill } from "../../components/Status";
import { StudioTabs } from "../../components/StudioTabs";
import { useRunEvents } from "../../hooks/useRunEvents";

function formatDate(value?: string | null) {
  return value ? new Date(value).toLocaleString() : "-";
}

function connectionLabel(state: string) {
  if (state === "live") return "实时连接中";
  if (state === "connecting") return "正在连接";
  if (state === "reconnecting") return "重连中";
  if (state === "error") return "连接异常";
  return "未连接";
}

export default function RunsPage() {
  const { caseId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const highlightedRunId = searchParams.get("run");
  const queryClient = useQueryClient();
  const caseDetail = useQuery({
    queryKey: ["case", caseId],
    queryFn: () => api.cases.detail(caseId),
    enabled: Boolean(caseId),
  });
  const runs = useQuery({
    queryKey: ["case-runs", caseId],
    queryFn: () => api.cases.runs(caseId, { limit: 100 }),
    enabled: Boolean(caseId),
  });
  const [selectedRunId, setSelectedRunId] = useState<string | null>(highlightedRunId);
  const selectedCard = useMemo(
    () => runs.data?.items.find((run) => run.runId === selectedRunId) ?? runs.data?.items[0],
    [runs.data?.items, selectedRunId],
  );
  const runDetail = useQuery({
    queryKey: ["run-detail", selectedCard?.runId],
    queryFn: () => api.runs.detail(selectedCard!.runId),
    enabled: Boolean(selectedCard?.runId),
  });
  const runEvents = useRunEvents(selectedCard?.runId, Boolean(selectedCard?.runId));
  const lastEventKey = runEvents.events.at(-1)?.event_id ?? runEvents.events.length;

  useEffect(() => {
    if (!selectedRunId && runs.data?.items[0]) {
      setSelectedRunId(runs.data.items[0].runId);
    }
  }, [runs.data?.items, selectedRunId]);

  useEffect(() => {
    if (!lastEventKey) return;
    void queryClient.invalidateQueries({ queryKey: ["case-runs", caseId] });
    if (selectedCard?.runId) {
      void queryClient.invalidateQueries({ queryKey: ["run-detail", selectedCard.runId] });
    }
  }, [caseId, lastEventKey, queryClient, selectedCard?.runId]);

  function selectRun(run: RunCard) {
    setSelectedRunId(run.runId);
    setSearchParams({ run: run.runId });
  }

  const cancelRun = useMutation({
    mutationFn: (runId: string) => api.runs.cancel(runId, { reason: "用户在前端取消", force: false }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["case-runs", caseId] });
      if (selectedCard?.runId) await queryClient.invalidateQueries({ queryKey: ["run-detail", selectedCard.runId] });
    },
  });
  const retryRun = useMutation({
    mutationFn: (runId: string) => api.runs.retry(runId, { reason: "前端重试" }),
    onSuccess: async (data) => {
      setSelectedRunId(data.run.id);
      setSearchParams({ run: data.run.id });
      await queryClient.invalidateQueries({ queryKey: ["case-runs", caseId] });
    },
    onError: (error: ApiError) => error,
  });
  const resumeRun = useMutation({
    mutationFn: (runId: string) => api.runs.resume(runId, { reason: "前端恢复", reuse_valid_artifacts: true }),
    onSuccess: async (data) => {
      setSelectedRunId(data.run.id);
      setSearchParams({ run: data.run.id });
      await queryClient.invalidateQueries({ queryKey: ["case-runs", caseId] });
    },
  });

  const items = runs.data?.items ?? [];
  const nodeRuns = runDetail.data?.node_runs ?? [];

  return (
    <section className="pageStack">
      <header className="pageHeader">
        <div>
          <h1>{caseDetail.data?.name ?? "Runs"}</h1>
          <p>{connectionLabel(runEvents.state)} · {items.length} 个 Run</p>
        </div>
      </header>
      <StudioTabs caseId={caseId} />
      {caseDetail.error ? <ErrorState error={caseDetail.error} /> : null}
      {runs.isLoading ? <LoadingState label="加载 Runs" /> : null}
      {runs.error ? <ErrorState error={runs.error} /> : null}
      {items.length === 0 && !runs.isLoading ? <EmptyState title="暂无 Runs" detail="从创作页提交任务后会实时出现在这里。" /> : null}

      {items.length > 0 ? (
        <div className="runsLayout">
          <div className="dataTable surface">
            <div className="tableRow tableHead runRow">
              <span>Run</span>
              <span>状态</span>
              <span>节点</span>
              <span>进度</span>
              <span>开始时间</span>
              <span>动作</span>
            </div>
            {items.map((run) => (
              <button
                type="button"
                className={`tableRow runRow rowButton ${run.runId === selectedCard?.runId ? "selected" : ""} ${run.runId === highlightedRunId ? "highlighted" : ""}`}
                onClick={() => selectRun(run)}
                key={run.runId}
              >
                <strong>{run.title}</strong>
                <StatusPill status={run.status} />
                <span>{run.currentNodeLabel ?? "-"}</span>
                <span className="progressCell">
                  <i style={{ width: `${Math.round(run.progress * 100)}%` }} />
                  <b>{Math.round(run.progress * 100)}%</b>
                </span>
                <span>{formatDate(run.startedAt)}</span>
                <span className="rowActions" onClick={(event) => event.stopPropagation()}>
                  <button
                    className="ghostButton compactButton"
                    type="button"
                    disabled={run.status !== "running" && run.status !== "admitted"}
                    onClick={() => cancelRun.mutate(run.runId)}
                  >
                    <Ban size={14} />
                    <span>取消</span>
                  </button>
                  <button
                    className="ghostButton compactButton"
                    type="button"
                    disabled={!run.canRetry}
                    onClick={() => retryRun.mutate(run.runId)}
                  >
                    <RotateCw size={14} />
                    <span>重试</span>
                  </button>
                  <button
                    className="ghostButton compactButton"
                    type="button"
                    disabled={!run.canResume}
                    onClick={() => resumeRun.mutate(run.runId)}
                  >
                    <Play size={14} />
                    <span>恢复</span>
                  </button>
                </span>
              </button>
            ))}
          </div>

          <aside className="surface timelinePanel">
            <div className="sectionHeader">
              <div>
                <h2>节点时间线</h2>
                <p>{selectedCard?.runId ?? "-"}</p>
              </div>
              {selectedCard ? <StatusPill status={selectedCard.status} /> : null}
            </div>
            {runDetail.isLoading ? <LoadingState label="加载节点" /> : null}
            {runDetail.error ? <ErrorState error={runDetail.error} /> : null}
            {nodeRuns.length === 0 && !runDetail.isLoading ? (
              <EmptyState title="暂无节点" detail="Run 入队后会显示节点推进。" />
            ) : null}
            <div className="timeline">
              {nodeRuns.map((node) => (
                <div className="timelineItem" key={node.id}>
                  <StatusPill status={node.status} />
                  <div>
                    <strong>{node.node_id}</strong>
                    <span>{formatDate(node.started_at)} - {formatDate(node.finished_at)}</span>
                    {(node.warnings?.length ?? 0) || (node.degradations?.length ?? 0) ? (
                      <p>{[...(node.warnings ?? []), ...(node.degradations ?? []).map((item) => item.code)].join(" / ")}</p>
                    ) : null}
                    {node.error ? <p className="dangerText">{node.error.message}</p> : null}
                  </div>
                </div>
              ))}
            </div>
          </aside>
        </div>
      ) : null}
    </section>
  );
}
