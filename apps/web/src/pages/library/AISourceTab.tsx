import { ArrowLeft, ArrowRight, FolderUp, ImageIcon, Loader2, Trash2, Video } from "lucide-react";
import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type MediaAssetCard, type UploadKind } from "../../api/client";
import { readCardThumbnailUrl } from "../../components/library/libraryInteractionModel";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { SearchInput } from "../../components/ui/SearchInput";
import { EmptyState, ErrorState, LoadingState } from "../../components/ui/State";
import { useToast } from "../../components/ui/Toast";
import { useUpload } from "../../hooks/useUpload";
import { formatRelativeTime, shortId } from "../../lib/format";

// AI素材 = media assets tagged ai_material (uploaded from this tab). Images use the
// dedicated `image` kind; videos use `video`. They stay out of the digital-human
// template pools (portrait/broll) and are what the Seedance @reference picker reads.
const AI_TAG = "ai_material";
const hasAiTag = (card: MediaAssetCard) => (card.asset.tags ?? []).includes(AI_TAG);

export function AISourceTab() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const upload = useUpload();
  const imageInputRef = useRef<HTMLInputElement>(null);
  const videoInputRef = useRef<HTMLInputElement>(null);
  const [caseSearch, setCaseSearch] = useState("");
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<MediaAssetCard | null>(null);

  const casesQuery = useQuery({
    queryKey: ["library", "cases", caseSearch],
    queryFn: () => api.cases.list({ limit: 80, search: caseSearch.trim() || null }),
  });
  const cases = casesQuery.data?.items ?? [];
  const selectedCase = cases.find((item) => item.id === selectedCaseId) ?? null;

  const imageQuery = useQuery({
    queryKey: ["library", "ai-source", selectedCaseId, "image"],
    queryFn: () => api.mediaAssets.list({ limit: 100, case_id: selectedCaseId, kind: "image" }),
    enabled: Boolean(selectedCaseId),
  });
  const videoQuery = useQuery({
    queryKey: ["library", "ai-source", selectedCaseId, "video"],
    queryFn: () => api.mediaAssets.list({ limit: 100, case_id: selectedCaseId, kind: "video" }),
    enabled: Boolean(selectedCaseId),
  });
  const imageCards = (imageQuery.data?.items ?? []).filter(hasAiTag);
  const videoCards = (videoQuery.data?.items ?? []).filter(hasAiTag);

  const uploadMut = useMutation({
    mutationFn: ({ file, kind }: { file: File; kind: UploadKind }) =>
      upload.uploadFile({ file, kind, caseId: selectedCaseId, metadata: { ai_material: "1", title: file.name } }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["library", "ai-source", selectedCaseId] });
      toast.success("上传成功", "素材已加入 AI素材库");
    },
    onError: (error) => toast.error("上传失败", error),
  });

  const deleteMut = useMutation({
    mutationFn: (assetId: string) => api.mediaAssets.delete(assetId),
    onError: (error) => toast.error("删除失败", error),
  });

  function onPick(input: HTMLInputElement | null, kind: UploadKind) {
    const file = input?.files?.[0];
    if (file) uploadMut.mutate({ file, kind });
    if (input) input.value = "";
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    const title = deleteTarget.asset.title;
    try {
      await deleteMut.mutateAsync(deleteTarget.asset.id);
      await queryClient.invalidateQueries({ queryKey: ["library", "ai-source", selectedCaseId] });
      toast.success("素材已删除", title);
      setDeleteTarget(null);
    } catch {
      // The mutation's onError already shows the toast; keep the dialog open.
    }
  }

  if (!selectedCaseId) {
    return (
      <section className="card grid gap-4">
        <div>
          <h2 className="text-xl font-semibold text-text-primary">选择案例</h2>
          <p className="mt-1 text-sm text-text-secondary">点击案例进入其 AI素材库（上传图片/视频，供创作时 @ 引用）。</p>
        </div>
        <SearchInput value={caseSearch} onChange={setCaseSearch} placeholder="搜索案例" />
        {casesQuery.isLoading ? <LoadingState label="加载案例" /> : null}
        {casesQuery.error ? <ErrorState error={casesQuery.error} /> : null}
        {!casesQuery.isLoading && !casesQuery.error && cases.length === 0 ? (
          <EmptyState title="暂无案例" detail="先在案例中心创建案例。" />
        ) : null}
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {cases.map((item) => (
            <button
              key={item.id}
              type="button"
              className="group rounded-[24px] border border-border/80 bg-white/65 p-4 text-left shadow-glow transition-all hover:-translate-y-0.5 hover:border-accent/25"
              onClick={() => setSelectedCaseId(item.id)}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <span className="badge bg-accent/10 text-accent">案例</span>
                  <h3 className="mt-3 truncate text-lg font-semibold text-text-primary">{item.name}</h3>
                  <p className="mt-1 font-mono text-xs text-text-tertiary">{shortId(item.id, 12)}</p>
                </div>
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-accent/10 text-accent transition-transform group-hover:translate-x-0.5">
                  <ArrowRight className="h-5 w-5" />
                </span>
              </div>
            </button>
          ))}
        </div>
      </section>
    );
  }

  const pending = uploadMut.isPending;
  return (
    <section className="grid gap-4">
      <input
        ref={imageInputRef}
        className="hidden"
        type="file"
        accept="image/*"
        onChange={() => onPick(imageInputRef.current, "image")}
      />
      <input
        ref={videoInputRef}
        className="hidden"
        type="file"
        accept="video/*"
        onChange={() => onPick(videoInputRef.current, "video")}
      />
      <div className="card grid gap-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <button className="icon-button mt-0.5" type="button" aria-label="返回案例" onClick={() => setSelectedCaseId(null)}>
              <ArrowLeft className="h-4 w-4" />
            </button>
            <div>
              <h2 className="text-xl font-semibold text-text-primary">{selectedCase?.name ?? "AI素材"}</h2>
              <p className="mt-1 text-sm text-text-secondary">上传图片/视频作为 Seedance 生成的参考素材，创作时可 @ 引用。</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn-secondary" type="button" disabled={pending} onClick={() => imageInputRef.current?.click()}>
              {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ImageIcon className="h-4 w-4" />}
              <span>上传图片</span>
            </button>
            <button className="btn-primary" type="button" disabled={pending} onClick={() => videoInputRef.current?.click()}>
              {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderUp className="h-4 w-4" />}
              <span>上传视频</span>
            </button>
          </div>
        </div>

        <AssetSection
          title="图片"
          icon={<ImageIcon className="h-4 w-4 text-accent" />}
          cards={imageCards}
          loading={imageQuery.isLoading}
          error={imageQuery.error}
          emptyHint="还没有 AI 图片素材，点「上传图片」添加。"
          onDelete={setDeleteTarget}
          deletingAssetId={deleteMut.isPending ? deleteTarget?.asset.id ?? null : null}
        />
        <AssetSection
          title="视频"
          icon={<Video className="h-4 w-4 text-accent" />}
          cards={videoCards}
          loading={videoQuery.isLoading}
          error={videoQuery.error}
          emptyHint="还没有 AI 视频素材，点「上传视频」添加。"
          onDelete={setDeleteTarget}
          deletingAssetId={deleteMut.isPending ? deleteTarget?.asset.id ?? null : null}
        />
      </div>
      <ConfirmDialog
        isOpen={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        onConfirm={confirmDelete}
        title="删除 AI素材"
        message={deleteTarget ? `确定删除「${deleteTarget.asset.title}」吗？` : ""}
        consequences={[
          "会从 AI素材库和创作参考素材选择器中移除",
          "已创建的历史任务记录不受影响",
          "源文件对象会作为审计 artifact 保留",
        ]}
        confirmText="删除"
        type="danger"
        isLoading={deleteMut.isPending}
      />
    </section>
  );
}

function AssetSection({
  title,
  icon,
  cards,
  loading,
  error,
  emptyHint,
  onDelete,
  deletingAssetId,
}: {
  title: string;
  icon: React.ReactNode;
  cards: MediaAssetCard[];
  loading: boolean;
  error: unknown;
  emptyHint: string;
  onDelete: (card: MediaAssetCard) => void;
  deletingAssetId: string | null;
}) {
  return (
    <div className="grid gap-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-base font-semibold text-text-primary">
          {icon}
          <span>{title}</span>
        </h3>
        <span className="badge bg-white/70 text-text-secondary">{cards.length} 个</span>
      </div>
      {loading ? <LoadingState label={`加载${title}素材`} /> : null}
      {error ? <ErrorState error={error} /> : null}
      {!loading && !error && cards.length === 0 ? <EmptyState title={`暂无${title}素材`} detail={emptyHint} /> : null}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
        {cards.map((card) => {
          const thumb = readCardThumbnailUrl(card);
          return (
            <div key={card.asset.id} className="overflow-hidden rounded-xl border border-border/70 bg-white/55">
              <div className="relative aspect-square bg-surface-hover">
                {thumb ? (
                  <img src={thumb} alt={card.asset.title} className="h-full w-full object-cover" />
                ) : (
                  <span className="flex h-full w-full items-center justify-center text-xs text-text-tertiary">无预览</span>
                )}
                <button
                  className="icon-button absolute right-2 top-2 h-8 w-8 bg-white/90 text-text-secondary shadow-sm hover:border-status-error/30 hover:text-status-error"
                  type="button"
                  title="删除素材"
                  aria-label={`删除素材 ${card.asset.title}`}
                  disabled={deletingAssetId === card.asset.id}
                  onClick={() => onDelete(card)}
                >
                  {deletingAssetId === card.asset.id ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Trash2 className="h-4 w-4" />
                  )}
                </button>
              </div>
              <div className="grid gap-0.5 p-2">
                <p className="truncate text-xs font-medium text-text-primary" title={card.asset.title}>
                  {card.asset.title}
                </p>
                <p className="font-mono text-[10px] text-text-tertiary">{formatRelativeTime(card.asset.created_at ?? "")}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
