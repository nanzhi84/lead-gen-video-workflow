import { Film } from "lucide-react";
import type { RunDetailResponse } from "../../api/client";
import { shortId } from "../../lib/format";

type BrollOverlayPreview = {
  id: string;
  assetId: string;
  title: string;
  start: number;
  end: number;
  confidence: number;
  keywords: string[];
  sceneName?: string;
};

export function BrollTimelinePreview({ detail }: { detail?: RunDetailResponse }) {
  const overlays = readBrollOverlays(detail);
  const duration = Math.max(1, ...overlays.map((item) => item.end));

  return (
    <section className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-base font-semibold text-text-primary">B-roll 插入点</h4>
        <span className="badge bg-white/70 text-text-secondary">{overlays.length} 命中</span>
      </div>

      {overlays.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border bg-white/55 p-5 text-sm font-medium text-text-secondary">0 命中</div>
      ) : (
        <>
          <div className="relative h-14 rounded-2xl border border-border/70 bg-surface-hover">
            {overlays.map((overlay, index) => {
              const left = Math.max(0, Math.min(98, (overlay.start / duration) * 100));
              const width = Math.max(4, Math.min(100 - left, ((overlay.end - overlay.start) / duration) * 100));
              return (
                <div
                  key={overlay.id}
                  className={`absolute top-3 flex h-8 items-center justify-center rounded-xl px-2 text-xs font-semibold text-white ${confidenceTone(
                    overlay.confidence,
                  )}`}
                  style={{ left: `${left}%`, width: `${width}%` }}
                  title={`#${index + 1} ${overlay.title} · confidence ${overlay.confidence.toFixed(2)}`}
                >
                  #{index + 1}
                </div>
              );
            })}
          </div>

          <div className="grid gap-2">
            {overlays.map((overlay, index) => (
              <div key={overlay.id} className="grid grid-cols-[72px_minmax(0,1fr)_auto] items-center gap-3 rounded-2xl border border-border/70 bg-white/60 p-3">
                <div className="flex aspect-video items-center justify-center rounded-xl bg-surface-hover text-text-tertiary">
                  <Film className="h-5 w-5" />
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-text-primary">
                    #{index + 1} {overlay.title}
                  </p>
                  <p className="mt-1 font-mono text-xs text-text-tertiary">
                    {shortId(overlay.assetId, 12)} · {overlay.start.toFixed(1)}s - {overlay.end.toFixed(1)}s
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {overlay.keywords.length > 0 ? (
                      overlay.keywords.map((keyword) => (
                        <span key={keyword} className="badge bg-surface-hover text-text-secondary">
                          {keyword}
                        </span>
                      ))
                    ) : (
                      <span className="badge bg-white/70 text-text-tertiary">无关键词</span>
                    )}
                  </div>
                </div>
                <span className={`badge ${overlay.confidence > 0.7 ? "badge-success" : overlay.confidence >= 0.4 ? "badge-warning" : "bg-orange-100 text-orange-700"}`}>
                  {Math.round(overlay.confidence * 100)}%
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function confidenceTone(confidence: number) {
  if (confidence > 0.7) return "bg-status-success";
  if (confidence >= 0.4) return "bg-status-warning";
  return "bg-orange-500";
}

function readBrollOverlays(detail?: RunDetailResponse): BrollOverlayPreview[] {
  const planArtifact = detail?.artifacts.find((artifact) => artifact.kind === "plan.broll");
  const payloads = (detail as (RunDetailResponse & { artifact_payloads?: Record<string, unknown> }) | undefined)?.artifact_payloads;
  const plan = asRecord(planArtifact ? payloads?.[planArtifact.artifact_id] : undefined);
  const rawOverlays = Array.isArray(plan?.overlays) ? plan.overlays : [];
  return rawOverlays.flatMap((value, index) => {
    const row = asRecord(value);
    const assetId = readString(row?.asset_id);
    const start = readNumber(row?.timeline_start);
    const end = readNumber(row?.timeline_end);
    if (!assetId || start === null || end === null || end <= start) return [];
    const sceneName = readString(row?.scene_name);
    const reason = readString(row?.reason);
    return [
      {
        id: readString(row?.overlay_id) ?? `${assetId}-${index}`,
        assetId,
        title: sceneName ?? reason ?? shortId(assetId, 12),
        start,
        end,
        confidence: readNumber(row?.confidence) ?? 0,
        keywords: readStringList(row?.matched_keywords),
        sceneName: sceneName ?? undefined,
      },
    ];
  });
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function readStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : [];
}
