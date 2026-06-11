import { Download, FileArchive, Loader2, Scissors } from "lucide-react";
import { useState } from "react";
import { editorHandoffApi, type EditorHandoffResult, type JianyingDraftResult } from "../../api/r6";
import { toDisplayUrl } from "../../lib/url";
import { useToast } from "../Toast";
import { ConfirmDialog } from "../ui/ConfirmDialog";

type ActionKind = "handoff" | "jianying";

type ResultState =
  | { type: "handoff"; value: EditorHandoffResult }
  | { type: "jianying"; value: JianyingDraftResult };

type Props = {
  finishedVideoId?: string | null;
  compact?: boolean;
};

export function EditorHandoffActions({ finishedVideoId, compact = false }: Props) {
  const toast = useToast();
  const [pendingAction, setPendingAction] = useState<ActionKind | null>(null);
  const [isRunning, setIsRunning] = useState<ActionKind | null>(null);
  const [result, setResult] = useState<ResultState | null>(null);
  const disabled = !finishedVideoId || Boolean(isRunning);

  async function runAction(action: ActionKind) {
    if (!finishedVideoId) return;
    setIsRunning(action);
    try {
      if (action === "handoff") {
        const value = await editorHandoffApi.createEditorHandoff(finishedVideoId, { format: "zip" });
        setResult({ type: "handoff", value });
        toast.success("交接包已生成", value.package_artifact.artifact_id);
      } else {
        const value = await editorHandoffApi.createJianyingDraft(finishedVideoId, { template_id: null });
        setResult({ type: "jianying", value });
        toast.success("剪映草稿已生成", value.package_artifact.artifact_id);
      }
    } catch (error) {
      toast.error(action === "handoff" ? "导出交接包失败" : "生成剪映草稿失败", error);
    } finally {
      setIsRunning(null);
      setPendingAction(null);
    }
  }

  return (
    <div className={compact ? "grid gap-2" : "grid gap-3 rounded-[20px] border border-border/70 bg-white/60 p-4"}>
      <div className="flex flex-wrap gap-2">
        <button className="btn-secondary compactButton" type="button" disabled={disabled} onClick={() => setPendingAction("jianying")}>
          {isRunning === "jianying" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Scissors className="h-4 w-4" />}
          <span>生成剪映草稿</span>
        </button>
        <button className="btn-secondary compactButton" type="button" disabled={disabled} onClick={() => setPendingAction("handoff")}>
          {isRunning === "handoff" ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileArchive className="h-4 w-4" />}
          <span>导出交接包</span>
        </button>
      </div>
      {!finishedVideoId ? <p className="text-xs text-text-tertiary">成片尚未落库，完成后可生成剪映草稿。</p> : null}
      {result ? <HandoffResult result={result} /> : null}
      <ConfirmDialog
        isOpen={Boolean(pendingAction)}
        onClose={() => setPendingAction(null)}
        onConfirm={() => {
          if (pendingAction) return runAction(pendingAction);
        }}
        isLoading={Boolean(isRunning)}
        type="info"
        title={pendingAction === "handoff" ? "确认导出编辑交接包" : "确认生成剪映草稿"}
        message="系统会基于当前成片创建新的编辑产物，不会修改或覆盖原成片文件。"
        consequences={["会新增一个 artifact 记录", "内部 sandbox:// 地址不会直接作为浏览器下载链接", "如需本地剪映打开，请验收环境使用签名下载或后端产物目录"]}
        confirmText={pendingAction === "handoff" ? "导出交接包" : "生成草稿"}
      />
    </div>
  );
}

function HandoffResult({ result }: { result: ResultState }) {
  const artifact = result.value.package_artifact;
  const safeUrl = toDisplayUrl(artifact.uri);
  const manifest = result.type === "handoff" ? result.value.manifest : result.value.draft_manifest;
  return (
    <details className="rounded-2xl border border-border/70 bg-surface p-3 text-sm">
      <summary className="cursor-pointer font-medium text-text-primary">
        {result.type === "handoff" ? "交接包 manifest" : "剪映草稿 manifest"}
      </summary>
      <div className="mt-3 grid gap-2">
        <p className="font-mono text-xs text-text-tertiary">{artifact.artifact_id} · {artifact.kind}</p>
        {safeUrl ? (
          <a className="btn-secondary w-fit text-sm no-underline" href={safeUrl} target="_blank" rel="noopener noreferrer">
            <Download className="h-4 w-4" />
            <span>下载产物</span>
          </a>
        ) : (
          <p className="text-xs text-text-tertiary">产物地址为内部 URI，已在前端净化，不直接打开。</p>
        )}
        <pre className="max-h-52 overflow-auto rounded-xl bg-white/70 p-3 text-xs text-text-secondary">
          {JSON.stringify(manifest, null, 2)}
        </pre>
      </div>
    </details>
  );
}
