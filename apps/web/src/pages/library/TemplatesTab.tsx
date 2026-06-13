import { CheckCircle2, Film, FolderUp, Video } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type MediaAssetRecord, type UploadKind } from "../../api/client";
import { AnnotationEditorModal } from "../../components/annotation/AnnotationEditorModal";
import { TemplateBatchActionBar } from "../../components/library/TemplateBatchActionBar";
import { TemplateAssetCard } from "../../components/library/TemplateAssetCard";
import { TemplateGridSkeleton } from "../../components/library/TemplateGridSkeleton";
import { TemplateUploadModal } from "../../components/library/TemplateUploadModal";
import { UploadPlaceholderCard } from "../../components/library/UploadPlaceholderCard";
import { UsageRankingPanel } from "../../components/library/UsageRankingPanel";
import { templateKindLabels, type TemplateKind, type UploadPlaceholder, toDisplayUrl } from "../../components/library/libraryModel";
import { SearchInput } from "../../components/ui/SearchInput";
import { useToast } from "../../components/ui/Toast";
import { InfiniteScrollSentinel } from "../../components/ui/InfiniteScrollSentinel";
import { usePageVisible } from "../../hooks/usePageVisible";
import { useUpload } from "../../hooks/useUpload";
import { shortId } from "../../lib/format";

export function TemplatesTab() {
  const toast = useToast();
  const pageVisible = usePageVisible();
  const queryClient = useQueryClient();
  const replaceUpload = useUpload();
  const replaceInputRef = useRef<HTMLInputElement>(null);
  const [caseSearch, setCaseSearch] = useState("");
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [kind, setKind] = useState<TemplateKind>("portrait");
  const [assetLimit, setAssetLimit] = useState(50);
  const [assetSearch, setAssetSearch] = useState("");
  const [sceneFilter, setSceneFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState<"all" | MediaAssetRecord["annotation_status"]>("all");
  const [batchMode, setBatchMode] = useState(false);
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([]);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [annotationAssetId, setAnnotationAssetId] = useState<string | null>(null);
  const [replaceTargetAssetId, setReplaceTargetAssetId] = useState<string | null>(null);
  const [placeholders, setPlaceholders] = useState<UploadPlaceholder[]>([]);
  const [previewUrls, setPreviewUrls] = useState<Record<string, string>>({});

  const casesQuery = useQuery({
    queryKey: ["library", "cases", caseSearch],
    queryFn: () => api.cases.list({ limit: 80, search: caseSearch.trim() || null }),
  });

  const cases = casesQuery.data?.items ?? [];

  useEffect(() => {
    if (!selectedCaseId && cases[0]?.id) setSelectedCaseId(cases[0].id);
  }, [cases, selectedCaseId]);
  useEffect(() => {
    setAssetLimit(50);
  }, [kind, selectedCaseId]);

  const portraitQuery = useQuery({
    queryKey: ["library", "media", selectedCaseId, "portrait", assetLimit],
    queryFn: () => api.mediaAssets.list({ limit: assetLimit, case_id: selectedCaseId, kind: "portrait" }),
    enabled: Boolean(selectedCaseId),
    refetchInterval: pageVisible ? 10_000 : false,
  });

  const brollQuery = useQuery({
    queryKey: ["library", "media", selectedCaseId, "broll", assetLimit],
    queryFn: () => api.mediaAssets.list({ limit: assetLimit, case_id: selectedCaseId, kind: "broll" }),
    enabled: Boolean(selectedCaseId),
    refetchInterval: pageVisible ? 10_000 : false,
  });

  const usageQuery = useQuery({
    queryKey: ["library", "usage-ranking", selectedCaseId, kind],
    queryFn: () => api.mediaAssets.usageRanking(kind, { case_id: selectedCaseId, top_n: 20 }),
    enabled: Boolean(selectedCaseId),
    refetchInterval: pageVisible ? 10_000 : false,
  });

  const activeQuery = kind === "portrait" ? portraitQuery : brollQuery;
  const activeItems = activeQuery.data?.items ?? [];
  const hasMoreAssets = Boolean(activeQuery.data && activeItems.length >= assetLimit);
  const selectedCase = cases.find((item) => item.id === selectedCaseId) ?? null;
  const usageByAssetId = useMemo(
    () => new Map((usageQuery.data?.items ?? []).map((item) => [item.asset_id, item])),
    [usageQuery.data],
  );
  const scenes = useMemo(() => {
    const values = new Set<string>();
    activeItems.forEach((card) => card.asset.tags?.forEach((tag) => values.add(tag)));
    return Array.from(values).sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
  }, [activeItems]);

  const filteredItems = useMemo(() => {
    const keyword = assetSearch.trim().toLowerCase();
    return activeItems.filter((card) => {
      const asset = card.asset;
      const matchesKeyword =
        !keyword ||
        asset.title.toLowerCase().includes(keyword) ||
        asset.id.toLowerCase().includes(keyword) ||
        (asset.tags ?? []).some((tag) => tag.toLowerCase().includes(keyword));
      const matchesScene = sceneFilter === "all" || (asset.tags ?? []).includes(sceneFilter);
      const matchesStatus = statusFilter === "all" || asset.annotation_status === statusFilter;
      return matchesKeyword && matchesScene && matchesStatus;
    });
  }, [activeItems, assetSearch, sceneFilter, statusFilter]);

  const visiblePlaceholders = placeholders.filter((item) => item.kind === kind);

  const rerunMutation = useMutation({
    mutationFn: (assetId: string) => api.annotations.rerun(assetId, { force: false }),
    onSuccess: async (response) => {
      await queryClient.invalidateQueries({ queryKey: ["library", "media", selectedCaseId] });
      toast.success("分析任务已提交", response.run_id ? `运行 ID：${shortId(response.run_id)}` : "沙箱环境已完成标注状态更新");
    },
    onError: (error) => toast.error("分析失败", error),
  });

  const stabilizeMutation = useMutation({
    mutationFn: (assetIds: string[]) => api.mediaAssets.batchStabilize({ asset_ids: assetIds }),
    onSuccess: async (response) => {
      await queryClient.invalidateQueries({ queryKey: ["library", "media", selectedCaseId] });
      const failed = response.results.filter((item) => item.status === "failed");
      if (failed.length > 0) {
        toast.warning("部分素材增稳失败", failed.map((item) => item.message || item.error_code).join("；"));
      } else {
        toast.success("批量增稳完成", `已处理 ${response.results.length} 个素材`);
      }
      setSelectedAssetIds([]);
    },
    onError: (error) => toast.error("批量增稳失败", error),
  });

  const replaceMutation = useMutation({
    mutationFn: async ({ assetId, file }: { assetId: string; file: File }) => {
      const result = await replaceUpload.uploadFile({
        file,
        kind: kind as UploadKind,
        caseId: selectedCaseId,
        metadata: { title: file.name, template_mode: "replace" },
      });
      return api.mediaAssets.replaceSource(assetId, { upload_session_id: result.upload_session.id });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["library", "media", selectedCaseId] });
      toast.success("素材原视频已替换", "标注和卡片位置已保留。");
    },
    onError: (error) => toast.error("替换失败", error),
    onSettled: () => {
      setReplaceTargetAssetId(null);
      if (replaceInputRef.current) replaceInputRef.current.value = "";
      replaceUpload.reset();
    },
  });

  async function autoReplaceUploads(uploadSessionIds: string[]) {
    const response = await api.mediaAssets.autoMatchReplace({
      case_id: selectedCaseId,
      kind,
      upload_session_ids: uploadSessionIds,
    });
    await queryClient.invalidateQueries({ queryKey: ["library", "media", selectedCaseId] });
    const matched = response.results.filter((item) => item.status === "matched").length;
    const pending = response.results.length - matched;
    if (pending > 0) {
      toast.warning("自动匹配替换完成", `已替换 ${matched} 个，${pending} 个需手动处理。`);
    } else {
      toast.success("自动匹配替换完成", `已替换 ${matched} 个素材。`);
    }
  }

  function openReplacePicker(assetId: string) {
    setReplaceTargetAssetId(assetId);
    replaceInputRef.current?.click();
  }

  function handleReplaceFile(file: File | undefined) {
    if (!file || !replaceTargetAssetId) return;
    replaceMutation.mutate({ assetId: replaceTargetAssetId, file });
  }

  async function ensurePreview(assetId: string) {
    if (previewUrls[assetId]) return previewUrls[assetId];
    try {
      const response = await api.mediaAssets.previewUrl(assetId);
      const displayUrl = toDisplayUrl(response.url);
      if (!displayUrl) {
        toast.info("素材预览暂不可用（待真实媒体接入）");
        return null;
      }
      setPreviewUrls((current) => ({ ...current, [assetId]: displayUrl }));
      return displayUrl;
    } catch (error) {
      toast.error("预览地址获取失败", error);
      return null;
    }
  }

  function setPlaceholder(update: UploadPlaceholder) {
    setPlaceholders((current) => {
      const exists = current.some((item) => item.id === update.id);
      return exists ? current.map((item) => (item.id === update.id ? update : item)) : [update, ...current];
    });
  }

  function clearSuccessfulPlaceholder(id: string) {
    window.setTimeout(() => {
      setPlaceholders((current) => current.filter((item) => item.id !== id));
    }, 900);
  }

  return (
    <section className="grid gap-4 xl:grid-cols-[290px_minmax(0,1fr)]">
      <aside className="card grid content-start gap-4">
        <div>
          <h2 className="text-lg font-semibold text-text-primary">案例</h2>
          <p className="mt-1 text-sm text-text-secondary">模板与 B-roll 按案例归档。</p>
        </div>
        <SearchInput value={caseSearch} onChange={setCaseSearch} placeholder="搜索案例" />
        <div className="grid max-h-[620px] gap-2 overflow-y-auto pr-1">
          {casesQuery.isLoading ? <p className="text-sm text-text-secondary">案例加载中...</p> : null}
          {cases.map((item) => (
            <button
              key={item.id}
              className={`rounded-2xl border p-3 text-left transition-all ${
                selectedCaseId === item.id ? "border-accent/25 bg-accent/10 text-accent" : "border-border/75 bg-white/55 text-text-primary hover:bg-white/80"
              }`}
              type="button"
              onClick={() => {
                setSelectedCaseId(item.id);
                setSelectedAssetIds([]);
              }}
            >
              <span className="block truncate text-sm font-semibold">{item.name}</span>
              <span className="mt-1 block truncate text-xs text-text-secondary">
                {item.owner_user_id ? `负责人 ${shortId(item.owner_user_id)}` : `${item.active_memory_count} 条记忆`}
              </span>
            </button>
          ))}
          {!casesQuery.isLoading && cases.length === 0 ? <p className="text-sm text-text-secondary">暂无案例。</p> : null}
        </div>
      </aside>

      <div className="card grid gap-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold text-text-primary">{selectedCase?.name ?? "选择案例"}</h2>
            <p className="mt-1 text-sm text-text-secondary">人像模板与 B-roll 共用上传与标注流程。</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn-secondary" type="button" onClick={() => setBatchMode((value) => !value)}>
              <CheckCircle2 className="h-4 w-4" />
              <span>{batchMode ? "退出批量" : "批量操作"}</span>
            </button>
            <button className="btn-primary" type="button" onClick={() => setUploadOpen(true)} disabled={!selectedCaseId}>
              <FolderUp className="h-4 w-4" />
              <span>上传素材</span>
            </button>
          </div>
        </div>

        <div className="tabs">
          {(["portrait", "broll"] as TemplateKind[]).map((item) => (
            <button key={item} className={`tabLink ${kind === item ? "active" : ""}`} type="button" onClick={() => setKind(item)}>
              {item === "portrait" ? <Video className="h-4 w-4" /> : <Film className="h-4 w-4" />}
              <span>{templateKindLabels[item]}</span>
              <span className="badge bg-white/70 text-text-secondary">
                {item === "portrait" ? (portraitQuery.data?.items.length ?? 0) : (brollQuery.data?.items.length ?? 0)}
              </span>
            </button>
          ))}
        </div>

        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_180px_190px]">
          <SearchInput value={assetSearch} onChange={setAssetSearch} placeholder="搜索标题、ID 或标签" />
          <select value={sceneFilter} onChange={(event) => setSceneFilter(event.target.value)}>
            <option value="all">全部场景</option>
            {scenes.map((scene) => (
              <option key={scene} value={scene}>
                {scene}
              </option>
            ))}
          </select>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)}>
            <option value="all">全部标注状态</option>
            <option value="pending">待标注</option>
            <option value="annotated">已标注</option>
            <option value="annotation_failed">标注失败</option>
          </select>
        </div>

        <UsageRankingPanel report={usageQuery.data} isLoading={usageQuery.isLoading} error={usageQuery.error} />

        {batchMode ? (
          <TemplateBatchActionBar
            selectedCount={selectedAssetIds.length}
            isStabilizing={stabilizeMutation.isPending}
            onStabilize={() => stabilizeMutation.mutate(selectedAssetIds)}
            onClear={() => setSelectedAssetIds([])}
          />
        ) : null}

        {activeQuery.isLoading ? <TemplateGridSkeleton /> : null}
        {activeQuery.error ? (
          <p className="rounded-2xl border border-status-error/30 bg-status-error/10 p-4 text-sm text-status-error">
            素材加载失败：{String(activeQuery.error)}
          </p>
        ) : null}

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {visiblePlaceholders.map((item) => (
            <UploadPlaceholderCard key={item.id} item={item} />
          ))}
          {filteredItems.map((card) => (
            <TemplateAssetCard
              key={card.asset.id}
              card={card}
              previewUrl={toDisplayUrl(previewUrls[card.asset.id] ?? card.preview_url)}
              batchMode={batchMode}
              selected={selectedAssetIds.includes(card.asset.id)}
              isAnalyzing={rerunMutation.isPending && rerunMutation.variables === card.asset.id}
              isReplacing={replaceMutation.isPending && replaceMutation.variables?.assetId === card.asset.id}
              usage={usageByAssetId.get(card.asset.id)}
              onToggleSelected={() =>
                setSelectedAssetIds((current) =>
                  current.includes(card.asset.id) ? current.filter((id) => id !== card.asset.id) : [...current, card.asset.id],
                )
              }
              onPreview={() => void ensurePreview(card.asset.id)}
              onAnalyze={() => rerunMutation.mutate(card.asset.id)}
              onReplaceSource={() => openReplacePicker(card.asset.id)}
              onOpenAnnotation={() => setAnnotationAssetId(card.asset.id)}
            />
          ))}
        </div>
        <InfiniteScrollSentinel
          enabled={hasMoreAssets && !activeQuery.isFetching}
          onVisible={() => setAssetLimit((current) => current + 50)}
          label={`继续加载${templateKindLabels[kind]}`}
        />

        {!activeQuery.isLoading && visiblePlaceholders.length === 0 && filteredItems.length === 0 ? (
          <div className="rounded-[24px] border border-dashed border-border bg-white/55 p-8 text-center">
            <Video className="mx-auto h-8 w-8 text-text-tertiary" />
            <p className="mt-3 text-sm font-medium text-text-primary">暂无{templateKindLabels[kind]}</p>
            <p className="mt-1 text-xs text-text-secondary">上传素材后会进入标注队列。</p>
          </div>
        ) : null}
      </div>

      <TemplateUploadModal
        isOpen={uploadOpen}
        onClose={() => setUploadOpen(false)}
        caseId={selectedCaseId}
        kind={kind}
        onPlaceholder={setPlaceholder}
        onSuccess={async (placeholderId) => {
          clearSuccessfulPlaceholder(placeholderId);
          await queryClient.invalidateQueries({ queryKey: ["library", "media", selectedCaseId] });
        }}
        onAutoReplace={autoReplaceUploads}
      />
      <input
        ref={replaceInputRef}
        className="hidden"
        type="file"
        accept=".mp4,.mov,.m4v,.webm,.avi,.mkv"
        onChange={(event) => handleReplaceFile(event.currentTarget.files?.[0])}
      />
      <AnnotationEditorModal assetId={annotationAssetId} caseId={selectedCaseId} onClose={() => setAnnotationAssetId(null)} />
    </section>
  );
}
