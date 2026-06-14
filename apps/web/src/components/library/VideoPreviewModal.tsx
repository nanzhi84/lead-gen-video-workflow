import { useMemo } from "react";
import { Clock, Download, Eye, FileVideo, Loader2, Tag } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api, type MediaAssetCard } from "../../api/client";
import { formatDuration, shortId } from "../../lib/format";
import {
  canonicalToQualityEvents,
  canonicalToSegments,
  readDuration,
  type AnnotationQualityEvent,
  type AnnotationTimelineSegment,
} from "../../utils/annotationV4";
import { Modal } from "../ui/Modal";
import { VideoPlayer, type VideoPlayerQualityEvent, type VideoPlayerSegment } from "../ui/VideoPlayer";
import { annotationStatusLabels, annotationTone, templateKindLabels, toDisplayUrl, type TemplateKind } from "./libraryModel";

type VideoPreviewModalProps = {
  /** Card to preview; `null` keeps the modal closed (open state is derived from this). */
  card: MediaAssetCard | null;
  /** Browser-playable preview URL (already sanitized via toDisplayUrl); `null` => unavailable. */
  previewUrl: string | null;
  onClose: () => void;
  /** Optional: open the annotation editor for this asset (footer shortcut). */
  onOpenAnnotation?: () => void;
};

/** Map an editor-flat segment to the player's segment shape (id/start/end/label/role). */
function toPlayerSegment(segment: AnnotationTimelineSegment, index: number): VideoPlayerSegment {
  const role = segment.usable_roles?.[0];
  const label = segment.summary || segment.retrieval_sentence || segment.segment_id || `片段 ${index + 1}`;
  return {
    id: segment.segment_id || `seg-${index}`,
    start: segment.start,
    end: segment.end,
    label,
    role,
  };
}

/** Map a canonical quality event to the player's marker shape. */
function toPlayerQualityEvent(event: AnnotationQualityEvent, index: number): VideoPlayerQualityEvent {
  return {
    id: event.event_id || `qe-${index}`,
    start: event.start,
    end: event.end,
    label: event.description || event.event_type || "质量事件",
    risk_tier: event.risk_tier,
  };
}

export function VideoPreviewModal({ card, previewUrl, onClose, onOpenAnnotation }: VideoPreviewModalProps) {
  const asset = card?.asset ?? null;
  const assetId = asset?.id ?? null;
  const isAnnotated = asset?.annotation_status === "annotated";

  // Only pull the canonical annotation when the asset is annotated — drives segment/quality overlays + duration.
  const annotationQuery = useQuery({
    queryKey: ["library", "annotation", assetId],
    queryFn: () => api.annotations.get(assetId!),
    enabled: Boolean(assetId) && isAnnotated,
  });

  const canonical = annotationQuery.data?.canonical;

  const segments = useMemo<VideoPlayerSegment[]>(() => {
    if (!canonical) return [];
    return canonicalToSegments(canonical).map(toPlayerSegment);
  }, [canonical]);

  const qualityEvents = useMemo<VideoPlayerQualityEvent[]>(() => {
    if (!canonical) return [];
    return canonicalToQualityEvents(canonical).map(toPlayerQualityEvent);
  }, [canonical]);

  const durationHint = useMemo(() => (canonical ? readDuration(canonical) : 0), [canonical]);

  if (!asset) return null;

  const kindLabel = templateKindLabels[asset.kind as TemplateKind] ?? asset.kind;
  const tags = asset.tags ?? [];
  const loadingOverlay = isAnnotated && annotationQuery.isLoading;

  return (
    <Modal isOpen={Boolean(card)} onClose={onClose} title={asset.title} size="2xl">
      <div className="grid gap-5">
        <div className="relative">
          {previewUrl ? (
            <VideoPlayer
              src={previewUrl}
              className="aspect-video w-full"
              autoPlay
              segments={segments}
              qualityEvents={qualityEvents}
              durationHint={durationHint > 0 ? durationHint : undefined}
            />
          ) : (
            <div className="grid aspect-video w-full place-items-center rounded-2xl border border-dashed border-border bg-[#151913] text-sm text-white/70">
              <div className="flex flex-col items-center gap-2">
                <FileVideo className="h-8 w-8 opacity-70" />
                <span>素材预览暂不可用（待真实媒体接入）</span>
              </div>
            </div>
          )}
          {loadingOverlay ? (
            <div className="pointer-events-none absolute right-3 top-3 flex items-center gap-2 rounded-full bg-black/65 px-3 py-1.5 text-xs text-white">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              <span>加载片段标记…</span>
            </div>
          ) : null}
        </div>

        <div className="grid gap-3">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-text-secondary">
            <span className="flex items-center gap-2">
              <FileVideo className="h-4 w-4 text-text-tertiary" />
              <span>类型：{kindLabel}</span>
            </span>
            <span className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-text-tertiary" />
              <span>时长：{durationHint > 0 ? formatDuration(durationHint) : "未知"}</span>
            </span>
            <span className="flex items-center gap-2">
              <span className="text-text-tertiary">标注：</span>
              <span className={`badge ${annotationTone(asset.annotation_status)}`}>
                {annotationStatusLabels[asset.annotation_status]}
              </span>
            </span>
            <span className="font-mono text-xs text-text-tertiary">{shortId(asset.id, 14)}</span>
          </div>

          {tags.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2">
              <Tag className="h-4 w-4 shrink-0 text-text-tertiary" />
              {tags.map((tag) => (
                <span key={tag} className="badge bg-surface-hover text-text-secondary">
                  {tag}
                </span>
              ))}
            </div>
          ) : null}

          {isAnnotated && !annotationQuery.isLoading ? (
            <p className="text-xs text-text-tertiary">
              {segments.length > 0
                ? `已叠加 ${segments.length} 个片段标记${qualityEvents.length > 0 ? ` · ${qualityEvents.length} 个质量事件` : ""}（点击时间轴可跳转）。`
                : "该标注暂无可视化片段。"}
            </p>
          ) : null}
        </div>

        <div className="flex flex-wrap justify-end gap-3 border-t border-border pt-4">
          {onOpenAnnotation ? (
            <button className="btn-secondary" type="button" onClick={onOpenAnnotation}>
              <Eye className="h-4 w-4" />
              <span>查看标注</span>
            </button>
          ) : null}
          {previewUrl ? (
            <a className="btn-secondary" href={previewUrl} download title="下载">
              <Download className="h-4 w-4" />
              <span>下载视频</span>
            </a>
          ) : null}
          <button className="btn-primary" type="button" onClick={onClose}>
            关闭
          </button>
        </div>
      </div>
    </Modal>
  );
}
