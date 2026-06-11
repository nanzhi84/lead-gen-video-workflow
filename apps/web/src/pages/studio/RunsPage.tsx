import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Download, Eye, Image as ImageIcon, Play, RotateCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api, type ApiError, type NodeRun, type RunCard, type RunDetailResponse } from "../../api/client";
import { EmptyState, ErrorState, LoadingState } from "../../components/State";
import { StatusPill } from "../../components/Status";
import { StudioTabs } from "../../components/StudioTabs";
import { TimeText } from "../../components/TimeText";
import { useToast } from "../../components/Toast";
import { Modal } from "../../components/ui/Modal";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { useRunEvents } from "../../hooks/useRunEvents";
import { usePageVisible } from "../../hooks/usePageVisible";
import { shortId } from "../../lib/format";

type RunAction = "cancel" | "retry" | "resume";

type PendingAction = {
  type: RunAction;
  run: RunCard;
};

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
  const toast = useToast();
  const pageVisible = usePageVisible();
  const caseDetail = useQuery({
    queryKey: ["case", caseId],
    queryFn: () => api.cases.detail(caseId),
    enabled: Boolean(caseId),
  });
  const runs = useQuery({
    queryKey: ["case-runs", caseId],
    queryFn: () => api.cases.runs(caseId, { limit: 100 }),
    enabled: Boolean(caseId),
    refetchInterval: pageVisible ? 10000 : false,
  });
  const [selectedRunId, setSelectedRunId] = useState<string | null>(highlightedRunId);
  const [detailOpen, setDetailOpen] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const selectedCard = useMemo(
    () => runs.data?.items.find((run) => run.runId === selectedRunId) ?? runs.data?.items[0],
    [runs.data?.items, selectedRunId],
  );
  const runDetail = useQuery({
    queryKey: ["run-detail", selectedCard?.runId],
    queryFn: () => api.runs.detail(selectedCard!.runId),
    enabled: Boolean(selectedCard?.runId),
    refetchInterval: pageVisible ? 10000 : false,
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

  function openRunDetail(run: RunCard) {
    selectRun(run);
    setDetailOpen(true);
  }

  const cancelRun = useMutation({
    mutationFn: (runId: string) => api.runs.cancel(runId, { reason: "用户在前端取消", force: false }),
    onSuccess: async () => {
      toast.success("已发送中断请求");
      await queryClient.invalidateQueries({ queryKey: ["case-runs", caseId] });
      if (selectedCard?.runId) await queryClient.invalidateQueries({ queryKey: ["run-detail", selectedCard.runId] });
    },
  });
  const retryRun = useMutation({
    mutationFn: (runId: string) => api.runs.retry(runId, { reason: "前端重试" }),
    onSuccess: async (data) => {
      toast.success("已复制配置并重新提交", shortId(data.run.id));
      setSelectedRunId(data.run.id);
      setSearchParams({ run: data.run.id });
      await queryClient.invalidateQueries({ queryKey: ["case-runs", caseId] });
    },
    onError: (error: ApiError) => error,
  });
  const resumeRun = useMutation({
    mutationFn: (runId: string) => api.runs.resume(runId, { reason: "前端恢复", reuse_valid_artifacts: true }),
    onSuccess: async (data) => {
      toast.success("已从失败阶段续跑", "将复用已完成节点的有效产物");
      setSelectedRunId(data.run.id);
      setSearchParams({ run: data.run.id });
      await queryClient.invalidateQueries({ queryKey: ["case-runs", caseId] });
    },
  });

  const items = runs.data?.items ?? [];
  const nodeRuns = runDetail.data?.node_runs ?? [];
  const confirmLoading =
    (pendingAction?.type === "cancel" && cancelRun.isPending) ||
    (pendingAction?.type === "retry" && retryRun.isPending) ||
    (pendingAction?.type === "resume" && resumeRun.isPending);

  async function confirmRunAction() {
    if (!pendingAction) return;
    if (pendingAction.type === "cancel") {
      await cancelRun.mutateAsync(pendingAction.run.runId);
    } else if (pendingAction.type === "retry") {
      await retryRun.mutateAsync(pendingAction.run.runId);
    } else {
      await resumeRun.mutateAsync(pendingAction.run.runId);
    }
    setPendingAction(null);
  }

  return (
    <section className="pageStack">
      <header className="pageHeader">
        <div>
          <h1>{caseDetail.data?.name ?? "成片"}</h1>
          <p>{connectionLabel(runEvents.state)} · {items.length} 个生成任务</p>
        </div>
      </header>
      <StudioTabs caseId={caseId} />
      {caseDetail.error ? <ErrorState error={caseDetail.error} /> : null}
      {runs.isLoading ? <LoadingState label="加载生成任务" /> : null}
      {runs.error ? <ErrorState error={runs.error} /> : null}
      {items.length === 0 && !runs.isLoading ? <EmptyState title="暂无生成任务" detail="从创作页提交任务后会实时出现在这里。" /> : null}

      {items.length > 0 ? (
        <div className="runsLayout">
          <div className="grid gap-4 xl:grid-cols-2">
            {items.map((run) => (
              <article
                className={`group flex min-h-[198px] cursor-pointer gap-4 rounded-[24px] border bg-[linear-gradient(180deg,rgba(255,255,252,0.9),rgba(249,250,244,0.96))] p-3 shadow-glow transition-all duration-200 hover:-translate-y-0.5 hover:border-accent/25 ${
                  run.runId === selectedCard?.runId ? "border-accent/25" : "border-border/80"
                } ${run.runId === highlightedRunId ? "ring-2 ring-accent/20" : ""}`}
                onClick={() => openRunDetail(run)}
                key={run.runId}
              >
                <div className="w-[96px] flex-none sm:w-[112px]">
                  <RunThumbnail run={run} />
                </div>

                <div className="flex min-w-0 flex-1 flex-col py-1">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <code className="rounded-full bg-accent/10 px-2.5 py-1 text-xs font-semibold text-accent">
                          {shortId(run.runId)}
                        </code>
                        <StatusPill status={run.status} />
                      </div>
                      <h2 className="line-clamp-2 text-base font-semibold text-text-primary">{run.title}</h2>
                      <p className="truncate text-sm text-text-secondary">{run.currentNodeLabel || "等待节点推进"}</p>
                    </div>
                  </div>

                  <div className="mt-3">
                    <div className="mb-1.5 flex items-center justify-between gap-3 text-xs text-text-tertiary">
                      <span>生产进度</span>
                      <span className="font-mono font-medium text-text-secondary">{Math.round(run.progress * 100)}%</span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-surface-hover">
                      <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${Math.round(run.progress * 100)}%` }} />
                    </div>
                  </div>

                  <div className="mt-3 grid grid-cols-1 gap-2 text-xs text-text-secondary sm:grid-cols-2">
                    <div className="min-w-0">
                      <p className="text-[11px] text-text-tertiary">开始时间</p>
                      <p className="truncate">
                        <TimeText value={run.startedAt} />
                      </p>
                    </div>
                    <div className="min-w-0">
                      <p className="text-[11px] text-text-tertiary">更新时间</p>
                      <p className="truncate">
                        <TimeText value={run.updatedAt} />
                      </p>
                    </div>
                  </div>

                  <div className="mt-auto flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-3">
                    <span className="badge-info">{run.canPublish ? "可创建发布包" : "等待成片"}</span>
                    <div className="flex items-center gap-1.5" onClick={(event) => event.stopPropagation()}>
                      <button className="rounded-lg p-2 text-text-tertiary hover:bg-surface hover:text-text-primary" type="button" onClick={() => openRunDetail(run)} title="查看详情">
                        <Eye className="h-4 w-4" />
                      </button>
                  <button
                    className="rounded-lg p-2 text-text-tertiary hover:bg-status-error/10 hover:text-status-error"
                    type="button"
                    disabled={run.status !== "running" && run.status !== "admitted"}
                    onClick={() => setPendingAction({ type: "cancel", run })}
                    title="中断生成任务"
                  >
                    <Ban className="h-4 w-4" />
                  </button>
                  <button
                    className="rounded-lg p-2 text-text-tertiary hover:bg-surface hover:text-text-primary"
                    type="button"
                    disabled={!run.canRetry}
                    onClick={() => setPendingAction({ type: "retry", run })}
                    title="重试"
                  >
                    <RotateCw className="h-4 w-4" />
                  </button>
                  <button
                    className="rounded-lg p-2 text-text-tertiary hover:bg-surface hover:text-text-primary"
                    type="button"
                    disabled={!run.canResume}
                    onClick={() => setPendingAction({ type: "resume", run })}
                    title="续跑"
                  >
                    <Play className="h-4 w-4" />
                  </button>
                    </div>
                  </div>
                </div>
              </article>
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
              <EmptyState title="暂无节点" detail="任务入队后会显示节点推进。" />
            ) : null}
            <div className="timeline">
              {nodeRuns.map((node) => (
                <div className="timelineItem" key={node.id}>
                  <StatusPill status={node.status} />
                  <div>
                    <strong>{node.node_id}</strong>
                    <span>
                      <TimeText value={node.started_at} /> - <TimeText value={node.finished_at} />
                    </span>
                    {(node.warnings?.length ?? 0) || (node.degradations?.length ?? 0) ? <p>存在警告或降级，详情见运行详情。</p> : null}
                    {node.error ? <p className="dangerText">{node.error.message}</p> : null}
                  </div>
                </div>
              ))}
            </div>
          </aside>
        </div>
      ) : null}

      <RunDetailModal
        isOpen={detailOpen}
        onClose={() => setDetailOpen(false)}
        card={selectedCard}
        detail={runDetail.data}
        isLoading={runDetail.isLoading}
        error={runDetail.error}
        onAction={(type, run) => setPendingAction({ type, run })}
      />

      <ConfirmDialog
        isOpen={Boolean(pendingAction)}
        onClose={() => setPendingAction(null)}
        onConfirm={confirmRunAction}
        isLoading={confirmLoading}
        type={pendingAction?.type === "cancel" ? "danger" : "warning"}
        title={confirmTitle(pendingAction)}
        message={confirmMessage(pendingAction)}
        consequences={confirmConsequences(pendingAction)}
        confirmText={confirmButtonText(pendingAction)}
      />
    </section>
  );
}

function RunThumbnail({ run }: { run: RunCard }) {
  return (
    <div className="group relative aspect-[9/16] w-full overflow-hidden rounded-[18px] border border-border/70 bg-[#20231f] shadow-sm">
      {run.previewUrl ? (
        <img
          src={run.previewUrl}
          alt={run.title}
          className="h-full w-full object-cover opacity-90 transition-opacity group-hover:opacity-100"
          loading="lazy"
          decoding="async"
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center bg-surface-hover">
          <ImageIcon className="h-7 w-7 text-text-tertiary" />
        </div>
      )}
      <div className="absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-black/60 to-transparent" />
      {run.status === "running" || run.status === "admitted" ? (
        <div className="absolute inset-0 flex items-center justify-center bg-black/20">
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-white/88 text-[#1b1d1a] shadow-lg">
            <Play className="h-5 w-5" />
          </span>
        </div>
      ) : null}
    </div>
  );
}

function RunDetailModal({
  isOpen,
  onClose,
  card,
  detail,
  isLoading,
  error,
  onAction,
}: {
  isOpen: boolean;
  onClose: () => void;
  card?: RunCard;
  detail?: RunDetailResponse;
  isLoading: boolean;
  error: unknown;
  onAction: (type: RunAction, run: RunCard) => void;
}) {
  const nodes = detail?.node_runs ?? [];
  const artifacts = detail?.artifacts ?? [];
  return (
    <Modal isOpen={isOpen} onClose={onClose} title={card ? `运行详情 ${shortId(card.runId)}` : "运行详情"} size="2xl">
      {!card ? <EmptyState title="暂无任务" /> : null}
      {isLoading ? <LoadingState label="加载运行详情" /> : null}
      {error ? <ErrorState error={error} /> : null}
      {card ? (
        <div className="grid gap-5">
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-start">
            <div>
              <h3 className="text-xl font-semibold text-text-primary">{card.title}</h3>
              <p className="mt-1 text-sm text-text-secondary">当前节点：{card.currentNodeLabel || "等待节点推进"}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button className="btn-secondary compactButton" type="button" disabled={card.status !== "running" && card.status !== "admitted"} onClick={() => onAction("cancel", card)}>
                <Ban className="h-4 w-4" />
                <span>中断</span>
              </button>
              <button className="btn-secondary compactButton" type="button" disabled={!card.canRetry} onClick={() => onAction("retry", card)}>
                <RotateCw className="h-4 w-4" />
                <span>重试</span>
              </button>
              <button className="btn-secondary compactButton" type="button" disabled={!card.canResume} onClick={() => onAction("resume", card)}>
                <Play className="h-4 w-4" />
                <span>续跑</span>
              </button>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-4">
            <DetailMetric label="状态" value={<StatusPill status={card.status} />} />
            <DetailMetric label="进度" value={`${Math.round(card.progress * 100)}%`} />
            <DetailMetric label="开始" value={<TimeText value={card.startedAt} />} />
            <DetailMetric label="更新" value={<TimeText value={card.updatedAt} />} />
          </div>

          <section className="grid gap-3">
            <h4 className="text-base font-semibold text-text-primary">节点时间线</h4>
            {nodes.length === 0 && !isLoading ? <EmptyState title="暂无节点" /> : null}
            <div className="grid gap-3">
              {nodes.map((node) => (
                <NodeDetail key={node.id} node={node} />
              ))}
            </div>
          </section>

          <section className="grid gap-3">
            <h4 className="text-base font-semibold text-text-primary">产物清单</h4>
            {artifacts.length === 0 ? <EmptyState title="暂无产物" detail="节点完成后会显示可下载产物。" /> : null}
            <div className="grid gap-2">
              {artifacts.map((artifact) => (
                <a
                  className="flex items-center justify-between gap-3 rounded-2xl border border-border/70 bg-white/60 p-3 no-underline hover:bg-white/80"
                  href={artifact.uri}
                  target="_blank"
                  rel="noopener noreferrer"
                  key={artifact.artifact_id}
                >
                  <div className="min-w-0">
                    <p className="truncate font-medium text-text-primary">{artifactLabel(artifact.kind)}</p>
                    <p className="truncate font-mono text-xs text-text-tertiary">{shortId(artifact.artifact_id, 12)} · {artifact.schema_version}</p>
                  </div>
                  <Download className="h-4 w-4 text-accent" />
                </a>
              ))}
            </div>
          </section>
        </div>
      ) : null}
    </Modal>
  );
}

function DetailMetric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-border/70 bg-white/60 p-3">
      <p className="text-xs text-text-tertiary">{label}</p>
      <div className="mt-1 text-sm font-medium text-text-primary">{value}</div>
    </div>
  );
}

function NodeDetail({ node }: { node: NodeRun }) {
  const warnings = [...(node.warnings ?? []), ...(node.degradations ?? []).map((item) => item.code)];
  return (
    <div className="grid gap-3 rounded-[20px] border border-border/70 bg-white/60 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-text-primary">{node.node_id}</p>
          <p className="text-xs text-text-secondary">
            <TimeText value={node.started_at} /> - <TimeText value={node.finished_at} />
          </p>
        </div>
        <StatusPill status={node.status} />
      </div>
      {warnings.length > 0 ? (
        <div className="grid gap-1 rounded-2xl border border-status-warning/20 bg-status-warning/10 p-3 text-sm text-status-warning">
          {warnings.map((warning) => (
            <p key={warning}>{warningLabel(warning)}</p>
          ))}
          {(node.degradations ?? []).map((notice) => (
            <p key={`${notice.code}-${notice.node_id ?? ""}`}>{notice.message || warningLabel(notice.code)}</p>
          ))}
        </div>
      ) : null}
      {node.error ? (
        <div className="grid gap-1 rounded-2xl border border-status-error/25 bg-status-error/10 p-3 text-sm text-status-error">
          <p className="font-medium">{node.error.message}</p>
          <p>严重级别：{severityLabel(node.error.severity)} · {node.error.retryable ? "可重试" : "不可重试"}</p>
          {node.error.request_id ? <p className="font-mono text-xs">request_id: {node.error.request_id}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

function warningLabel(value: string) {
  if (value === "broll.skipped_no_material") return "B-roll 素材不足，已跳过插入";
  if (value === "bgm.skipped_library_unannotated") return "BGM 库未完成标注，已跳过配乐";
  if (value === "font_default_used") return "指定字体不可用，已使用默认字体";
  if (value === "cover.frame_fallback") return "封面生成降级为取帧";
  if (value === "timestamp.estimated") return "部分时间戳为系统估算";
  if (value === "cost.unpriced") return "部分供应商费用未定价";
  return "未知警告";
}

function severityLabel(value: string) {
  if (value === "info") return "提示";
  if (value === "warning") return "警告";
  if (value === "fatal") return "致命";
  return "错误";
}

function artifactLabel(value: string) {
  if (value === "video.final" || value === "video.finished") return "最终视频";
  if (value === "video.rendered") return "渲染视频";
  if (value === "subtitle.ass") return "字幕文件";
  if (value === "cover.image") return "封面图片";
  if (value === "audio.tts") return "配音音频";
  if (value === "publish.package") return "发布包";
  if (value === "run.report.public") return "公开报告";
  if (value === "run.report.debug") return "调试报告";
  return "运行产物";
}

function confirmTitle(action: PendingAction | null) {
  if (action?.type === "cancel") return "确认中断生成任务";
  if (action?.type === "retry") return "确认重试任务";
  if (action?.type === "resume") return "确认续跑任务";
  return "确认操作";
}

function confirmMessage(action: PendingAction | null) {
  if (action?.type === "cancel") return "系统会请求停止当前生成链路，已完成产物会保留在运行记录中。";
  if (action?.type === "retry") return "系统会复制当前配置并创建新的生成任务，可能产生新的供应商费用。";
  if (action?.type === "resume") return "系统会从失败阶段继续执行，并复用已完成节点的有效产物。";
  return "请确认是否继续。";
}

function confirmConsequences(action: PendingAction | null) {
  if (action?.type === "cancel") return ["不会删除已生成文件", "任务会进入中断中，最终状态由后端工作流确认"];
  if (action?.type === "retry") return ["会创建新的 Run", "会重新调用必要供应商能力并可能计费"];
  if (action?.type === "resume") return ["会复用可用产物", "只从失败或待恢复阶段继续执行"];
  return [];
}

function confirmButtonText(action: PendingAction | null) {
  if (action?.type === "cancel") return "确认中断";
  if (action?.type === "retry") return "确认重试";
  if (action?.type === "resume") return "确认续跑";
  return "确认";
}
