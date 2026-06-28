import { ImagePlus, Loader2, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import type { ArtifactRef, PublishBatchItem, PublishPackage } from "../../api/client";
import { useUpload } from "../../hooks/useUpload";
import { useToast } from "../ui/Toast";
import { toDisplayUrl } from "../../lib/url";
import type { PublishDraft } from "./publishModel";

type CoverPanelProps = {
  item: PublishBatchItem;
  draft: PublishDraft;
  publishPackage?: PublishPackage;
  originalCoverArtifact?: ArtifactRef | null;
  onCoverArtifact: (packageId: string, artifactId: string | null) => Promise<void>;
};

export function CoverPanel({ item, draft, publishPackage, originalCoverArtifact, onCoverArtifact }: CoverPanelProps) {
  const toast = useToast();
  const upload = useUpload();
  const [localCoverPreview, setLocalCoverPreview] = useState<string | null>(null);
  const [isRestoring, setIsRestoring] = useState(false);

  const videoUrl = artifactDisplayUrl(publishPackage?.video_artifact);
  const coverUrl = localCoverPreview ?? artifactDisplayUrl(publishPackage?.cover_artifact);
  const packageId = publishPackage?.id ?? item.publish_package_id;
  const currentCoverId = publishPackage?.cover_artifact?.artifact_id ?? null;
  const originalCoverId = originalCoverArtifact?.artifact_id ?? null;
  const isUsingOriginalCover = Boolean(originalCoverId && currentCoverId === originalCoverId);
  const isUploading = upload.status === "preparing" || upload.status === "uploading" || upload.status === "completing";
  const isBusy = isUploading || isRestoring;

  useEffect(() => {
    setLocalCoverPreview(null);
  }, [currentCoverId]);

  async function uploadCoverFile(file: File) {
    if (!publishPackage) {
      toast.error("缺少发布包", "请刷新批次后重试。");
      return;
    }
    const result = await upload.uploadFile({
      file,
      kind: "cover_template",
      caseId: publishPackage.case_id,
      metadata: { title: `${draft.title || "发布封面"}.jpg` },
    });
    await onCoverArtifact(packageId, result.artifact.artifact_id);
    setLocalCoverPreview(artifactDisplayUrl(result.artifact));
    toast.success("封面已上传", draft.title || item.id.slice(0, 8));
  }

  async function restoreOriginalCover() {
    if (!originalCoverArtifact) return;
    try {
      setIsRestoring(true);
      setLocalCoverPreview(null);
      await onCoverArtifact(packageId, originalCoverArtifact.artifact_id);
      toast.success("已使用原始封面");
    } catch (error) {
      toast.error("恢复原始封面失败", error);
    } finally {
      setIsRestoring(false);
    }
  }

  return (
    <details className="group rounded-2xl border border-dashed border-border bg-white/55 p-4" open>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-text-primary [&::-webkit-details-marker]:hidden">
        <span>封面{coverUrl ? "已设置" : "未设置"}</span>
        <span className="text-xs text-text-tertiary">视频预览 / 上传封面</span>
      </summary>
      <div className="mt-4 grid gap-4 lg:grid-cols-[160px_minmax(0,1fr)]">
        <div className="aspect-[9/16] self-start overflow-hidden rounded-2xl border border-border bg-surface">
          {coverUrl ? (
            <img src={coverUrl} alt="封面预览" className="h-full w-full object-cover" />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-text-tertiary">
              <ImagePlus className="h-8 w-8" />
            </div>
          )}
        </div>
        <div className="grid gap-3">
          {videoUrl ? (
            <video
              src={videoUrl}
              controls
              preload="metadata"
              playsInline
              poster={coverUrl ?? undefined}
              className="aspect-video w-full rounded-2xl border border-border bg-black object-contain"
            />
          ) : (
            <div className="flex min-h-28 items-center justify-center rounded-2xl border border-border bg-surface-hover/40 px-4 text-center text-sm text-text-secondary">
              当前发布包没有可预览视频。
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <label className="btn-secondary cursor-pointer">
              {isUploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ImagePlus className="h-4 w-4" />}
              上传封面
              <input
                type="file"
                className="hidden"
                accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
                disabled={isBusy}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void uploadCoverFile(file).catch((error) => toast.error("封面上传失败", error));
                  event.currentTarget.value = "";
                }}
              />
            </label>
            <button
              className="btn-secondary"
              type="button"
              disabled={!originalCoverArtifact || isUsingOriginalCover || isBusy}
              onClick={() => void restoreOriginalCover()}
            >
              {isRestoring ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
              使用原始封面
            </button>
          </div>
          <p className="rounded-2xl border border-status-info/25 bg-status-info/10 p-3 text-xs leading-5 text-status-info">
            发布页只展示当前发布包视频和封面；新封面请在生成链路产出，或在这里上传替换。
          </p>
        </div>
      </div>
    </details>
  );
}

function artifactDisplayUrl(artifact: ArtifactRef | null | undefined): string | null {
  if (!artifact) return null;
  return toDisplayUrl(artifact.uri) ?? `/api/artifacts/${artifact.artifact_id}/download`;
}
