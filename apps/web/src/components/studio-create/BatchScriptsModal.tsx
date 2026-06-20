import { Loader2, Play } from "lucide-react";
import { useMemo, useState } from "react";
import { Modal } from "../ui/Modal";
import { BATCH_MAX_ITEMS, parsePastedScripts, type BatchScriptInput } from "./batchModel";

type Props = {
  isOpen: boolean;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (inputs: BatchScriptInput[]) => void;
};

/**
 * Paste/import multiple scripts (one per blank-line-separated block) and submit
 * them as a single server-side batch. Each block becomes one job.
 */
export function BatchScriptsModal({ isOpen, isSubmitting, onClose, onSubmit }: Props) {
  const [raw, setRaw] = useState("");
  const blocks = useMemo(() => parsePastedScripts(raw), [raw]);
  const overLimit = blocks.length > BATCH_MAX_ITEMS;

  function submit() {
    if (blocks.length === 0 || overLimit) return;
    onSubmit(blocks.map((script) => ({ script })));
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="批量脚本出片" size="2xl">
      <div className="grid gap-4">
        <p className="text-sm text-text-secondary">
          每段脚本用<strong>空行</strong>分隔，提交后每段生成一个独立任务，套用你的默认配置。单次最多 {BATCH_MAX_ITEMS} 条。
        </p>
        <textarea
          className="min-h-[44vh] w-full resize-y rounded-2xl border border-border/70 bg-white/55 p-3 text-sm leading-relaxed"
          value={raw}
          onChange={(event) => setRaw(event.target.value)}
          placeholder={"第一条脚本正文…\n\n第二条脚本正文…\n\n第三条脚本正文…"}
          disabled={isSubmitting}
        />
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-text-secondary">
          <span>
            已识别 <strong className={overLimit ? "text-status-warning" : "text-text-primary"}>{blocks.length}</strong> 条
            {overLimit ? `（超过上限 ${BATCH_MAX_ITEMS}）` : ""}
          </span>
          <button
            className="btn-primary"
            type="button"
            disabled={blocks.length === 0 || overLimit || isSubmitting}
            onClick={submit}
          >
            {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            <span>批量出片 {blocks.length ? `(${blocks.length})` : ""}</span>
          </button>
        </div>
      </div>
    </Modal>
  );
}
