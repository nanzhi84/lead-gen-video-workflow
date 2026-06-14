import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  GitCompare,
  HelpCircle,
  Link2,
  Plus,
  RotateCcw,
  Send,
  ToggleLeft,
  ToggleRight,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type ApiError, type PromptBindingView } from "../../api/client";
import { Modal } from "../../components/Modal";
import { EmptyState, ErrorState, LoadingState } from "../../components/State";
import { TimeText } from "../../components/TimeText";
import { useToast } from "../../components/Toast";
import {
  BINDING_EXPLAINER,
  diffRows,
  emptyBinding,
  emptyTemplate,
  flow,
  promptGroups,
  schemaText,
  statusLabel,
  templateUsage,
  variableChips,
  type BindingForm,
  type PromptGroupKey,
  type TemplateForm,
} from "./promptManagementUtils";

/** 行内 ? 提示，鼠标悬停展示「绑定」的定义。 */
function BindingHint() {
  return (
    <span className="group relative inline-flex">
      <button
        type="button"
        className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-border/70 bg-white/70 text-text-tertiary transition-colors hover:border-accent/30 hover:text-text-secondary"
        aria-label="什么是绑定？"
      >
        <HelpCircle className="h-3.5 w-3.5" />
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute left-1/2 top-full z-20 mt-2 w-64 -translate-x-1/2 rounded-2xl border border-border bg-surface px-3 py-2 text-xs leading-relaxed text-text-secondary opacity-0 shadow-xl transition-opacity duration-150 group-hover:opacity-100"
      >
        {BINDING_EXPLAINER}
      </span>
    </span>
  );
}

/** 生产使用状态徽标：绿色「生产使用中」/ 灰色「未接入生产」。 */
function UsageBadge({ usage }: { usage: ReturnType<typeof templateUsage> }) {
  if (usage.inProduction) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-status-success/15 px-2.5 py-1 text-xs font-medium text-status-success">
        <span className="h-1.5 w-1.5 rounded-full bg-status-success" />
        {usage.label}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-black/5 px-2.5 py-1 text-xs font-medium text-text-tertiary">
      <span className="h-1.5 w-1.5 rounded-full bg-text-tertiary/60" />
      {usage.label}
    </span>
  );
}

/** 版本状态步进器：草稿 → 审批中 → 已审批 → 已发布，高亮当前选中版本所处状态。 */
function StatusStepper({ status }: { status?: string }) {
  const activeIndex = flow.indexOf((status ?? "") as (typeof flow)[number]);
  return (
    <div className="inline-flex w-full items-stretch overflow-hidden rounded-2xl border border-border/70 bg-white/60 text-xs font-medium sm:w-auto">
      {flow.map((step, index) => {
        const isActive = index === activeIndex;
        const isDone = activeIndex >= 0 && index < activeIndex;
        return (
          <div
            key={step}
            className={`flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap px-3 py-1.5 transition-colors sm:flex-none ${
              index > 0 ? "border-l border-border/60" : ""
            } ${
              isActive
                ? "bg-accent text-[#1b1d1a]"
                : isDone
                  ? "bg-accent/15 text-text-secondary"
                  : "text-text-tertiary"
            }`}
          >
            <span
              className={`flex h-4 w-4 items-center justify-center rounded-full text-[10px] leading-none ${
                isActive ? "bg-[#1b1d1a] text-accent" : isDone ? "bg-accent/40 text-text-secondary" : "bg-black/5 text-text-tertiary"
              }`}
            >
              {isDone ? "✓" : index + 1}
            </span>
            {statusLabel[step]}
          </div>
        );
      })}
    </div>
  );
}

export default function PromptManagementPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const [activeGroup, setActiveGroup] = useState<PromptGroupKey>("script");
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [templateForm, setTemplateForm] = useState<TemplateForm>(emptyTemplate);
  const [createOpen, setCreateOpen] = useState(false);
  const [draftContent, setDraftContent] = useState("");
  const [changelog, setChangelog] = useState("");
  const [bindingForm, setBindingForm] = useState<BindingForm>(emptyBinding);

  const templates = useQuery({ queryKey: ["prompts"], queryFn: () => api.prompts.list({ limit: 100 }) });
  const bindings = useQuery({
    queryKey: ["prompts", "bindings"],
    queryFn: () => api.prompts.bindings({ limit: 100 }),
  });

  const templateItems = useMemo(() => templates.data?.items ?? [], [templates.data?.items]);
  const activeGroupConfig = promptGroups.find((group) => group.key === activeGroup) ?? promptGroups[0];
  const groupedTemplateItems = useMemo(
    () => templateItems.filter((item) => item.template.purpose.startsWith(activeGroupConfig.prefix)),
    [activeGroupConfig.prefix, templateItems],
  );
  const selectedTemplate = groupedTemplateItems.find((item) => item.template.id === selectedTemplateId) ?? groupedTemplateItems[0];
  const currentTemplateId = selectedTemplate?.template.id ?? "";
  const versions = useQuery({
    queryKey: ["prompts", currentTemplateId, "versions"],
    queryFn: () => api.prompts.versions(currentTemplateId, { limit: 100 }),
    enabled: Boolean(currentTemplateId),
  });
  const versionItems = useMemo(() => versions.data?.items ?? [], [versions.data?.items]);
  const bindingItems = useMemo(() => bindings.data?.items ?? [], [bindings.data?.items]);
  const selectedVersion = versionItems.find((item) => item.version.id === selectedVersionId)?.version ?? versionItems[0]?.version;
  const publishedVersion = selectedTemplate?.published_version ?? null;
  const defaultVersion = versionItems.find((item) => item.version.id === `${currentTemplateId}_v1`)?.version;
  const selectedBindings = bindingItems.filter((item) => item.binding.prompt_template_id === selectedTemplate?.template.id);
  const selectedUsage = templateUsage(bindingItems, currentTemplateId);
  const rows = diffRows(publishedVersion?.content, selectedVersion?.content ?? draftContent);

  useEffect(() => {
    if (!groupedTemplateItems.some((item) => item.template.id === selectedTemplateId)) {
      setSelectedTemplateId(groupedTemplateItems[0]?.template.id ?? "");
    }
  }, [groupedTemplateItems, selectedTemplateId]);

  useEffect(() => {
    const first = versionItems[0]?.version;
    setSelectedVersionId((current) => (current && versionItems.some((item) => item.version.id === current) ? current : first?.id ?? ""));
  }, [versionItems]);

  useEffect(() => {
    if (selectedTemplate) {
      setDraftContent(publishedVersion?.content ?? selectedVersion?.content ?? "");
      setBindingForm((current) => ({ ...current, node_id: current.node_id || selectedTemplate.template.purpose }));
    }
  }, [publishedVersion?.content, selectedTemplate, selectedVersion?.content]);

  const invalidatePrompts = async () => {
    await queryClient.invalidateQueries({ queryKey: ["prompts"] });
  };

  const createTemplate = useMutation({
    mutationFn: () =>
      api.prompts.create({
        name: templateForm.name.trim(),
        purpose: templateForm.purpose.trim(),
        variables_schema_ref: { schema_id: templateForm.variables_schema_id.trim(), schema_version: "v1" },
        output_schema_ref: { schema_id: templateForm.output_schema_id.trim(), schema_version: "v1" },
      }),
    onSuccess: async (created) => {
      setTemplateForm(emptyTemplate);
      setCreateOpen(false);
      const createdGroup = promptGroups.find((group) => created.template.purpose.startsWith(group.prefix));
      if (createdGroup) setActiveGroup(createdGroup.key);
      setSelectedTemplateId(created.template.id);
      await invalidatePrompts();
      toast.success("提示词模板已创建", created.template.name);
    },
    onError: (error: ApiError) => toast.error("创建失败", error),
  });

  const createVersion = useMutation({
    mutationFn: () =>
      api.prompts.createVersion(currentTemplateId, {
        content: draftContent,
        changelog: changelog.trim() || null,
      }),
    onSuccess: async (created) => {
      setChangelog("");
      setSelectedVersionId(created.version.id);
      await invalidatePrompts();
      toast.success("草稿版本已保存", created.version.id);
    },
    onError: (error: ApiError) => toast.error("保存失败", error),
  });

  const approve = useMutation({
    mutationFn: (versionId: string) => api.prompts.approveVersion(currentTemplateId, versionId, { reason: "ops approval" }),
    onSuccess: async () => {
      await invalidatePrompts();
      toast.success("版本已审批");
    },
    onError: (error: ApiError) => toast.error("审批失败", error),
  });

  const publish = useMutation({
    mutationFn: (versionId: string) => api.prompts.publishVersion(currentTemplateId, versionId, { reason: "ops publish" }),
    onSuccess: async () => {
      await invalidatePrompts();
      toast.success("版本已发布");
    },
    onError: (error: ApiError) => toast.error("发布失败", error),
  });

  const rollback = useMutation({
    mutationFn: (versionId: string) =>
      api.prompts.rollback(currentTemplateId, { target_version_id: versionId, reason: "restore default v1" }),
    onSuccess: async () => {
      await invalidatePrompts();
      toast.success("已恢复默认版本");
    },
    onError: (error: ApiError) => toast.error("回滚失败", error),
  });

  const createBinding = useMutation({
    mutationFn: () =>
      api.prompts.createBinding({
        prompt_template_id: currentTemplateId,
        prompt_version_id: selectedVersion?.id || publishedVersion?.id || "",
        case_id: bindingForm.case_id.trim() || null,
        node_id: bindingForm.node_id.trim() || null,
        priority: bindingForm.priority,
      }),
    onSuccess: async () => {
      setBindingForm(emptyBinding);
      await queryClient.invalidateQueries({ queryKey: ["prompts", "bindings"] });
      toast.success("绑定已创建");
    },
    onError: (error: ApiError) => toast.error("绑定失败", error),
  });

  const patchBinding = useMutation({
    mutationFn: (binding: PromptBindingView) =>
      api.prompts.patchBinding(binding.binding.id, { enabled: !binding.binding.enabled }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["prompts", "bindings"] });
      toast.success("绑定已更新");
    },
    onError: (error: ApiError) => toast.error("更新失败", error),
  });

  const insertVariable = (name: string) => {
    const token = `{${name}}`;
    const editor = editorRef.current;
    if (!editor) {
      setDraftContent((value) => `${value}${value.endsWith(" ") || !value ? "" : " "}${token}`);
      return;
    }
    const start = editor.selectionStart ?? draftContent.length;
    const end = editor.selectionEnd ?? start;
    const next = `${draftContent.slice(0, start)}${token}${draftContent.slice(end)}`;
    const cursor = start + token.length;
    setDraftContent(next);
    window.requestAnimationFrame(() => {
      editor.focus();
      editor.setSelectionRange(cursor, cursor);
    });
  };

  const createDisabled = createTemplate.isPending || !templateForm.name.trim() || !templateForm.purpose.trim();

  return (
    <section className="pageStack">
      <header className="pageHeader">
        <div>
          <h1>提示词</h1>
          <p className="flex flex-wrap items-center gap-1.5">
            按生产用途管理已发布提示词，生产环境读取已发布版本。
            <span className="inline-flex items-center gap-1.5 text-text-tertiary">
              · {BINDING_EXPLAINER}
            </span>
          </p>
        </div>
      </header>

      <div className="flex flex-wrap gap-2" role="tablist" aria-label="提示词分组">
        {promptGroups.map((group) => {
          const count = templateItems.filter((item) => item.template.purpose.startsWith(group.prefix)).length;
          const active = group.key === activeGroup;
          return (
            <button
              aria-selected={active}
              className={`rounded-full border px-3 py-1.5 text-sm transition-colors ${active ? "border-accent bg-accent/15 text-text-primary" : "border-border/70 bg-white/70 text-text-secondary hover:bg-hover"}`}
              key={group.key}
              role="tab"
              type="button"
              onClick={() => setActiveGroup(group.key)}
            >
              {group.label} · {count}
            </button>
          );
        })}
      </div>

      {templates.isLoading ? <LoadingState /> : null}
      {templates.error ? <ErrorState error={templates.error} /> : null}
      {!templates.isLoading && templateItems.length === 0 ? <EmptyState title="暂无提示词" detail="创建模板后可保存版本。" /> : null}

      <div className="grid gap-5 xl:grid-cols-[300px_minmax(0,1fr)]">
        {/* 左列：仅模板列表 + 新建按钮 */}
        <aside className="grid content-start gap-3">
          <div className="card flex items-center justify-between gap-3 p-4">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-text-primary">{activeGroupConfig.label}</p>
              <p className="text-xs text-text-tertiary">{groupedTemplateItems.length} 个模板</p>
            </div>
            <button className="btn-primary shrink-0 px-3 py-2 text-sm" type="button" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" />
              <span>新建模板</span>
            </button>
          </div>

          <div className="card max-h-[calc(100vh-16rem)] overflow-y-auto p-0 xl:max-h-[calc(100vh-13rem)]">
            <div className="divide-y divide-border/60">
              {groupedTemplateItems.map((item) => {
                const usage = templateUsage(bindingItems, item.template.id);
                const isSelected = selectedTemplate?.template.id === item.template.id;
                return (
                  <button
                    className={`block w-full px-4 py-3 text-left transition-colors hover:bg-hover ${isSelected ? "bg-accent/10" : ""}`}
                    key={item.template.id}
                    type="button"
                    onClick={() => setSelectedTemplateId(item.template.id)}
                  >
                    <UsageBadge usage={usage} />
                    <span className="mt-2 block truncate text-sm font-semibold text-text-primary">{item.template.name}</span>
                    <span className="mt-0.5 block truncate font-mono text-xs text-text-tertiary">{item.template.purpose}</span>
                  </button>
                );
              })}
              {groupedTemplateItems.length === 0 ? (
                <div className="px-4 py-8 text-center text-sm text-text-secondary">
                  当前分组暂无模板。
                  <button className="mt-3 block w-full text-accent hover:underline" type="button" onClick={() => setCreateOpen(true)}>
                    + 新建第一个模板
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </aside>

        {/* 右列：详情面板 */}
        {selectedTemplate ? (
          <div className="grid gap-5">
            {/* 头部 + 编辑器 */}
            <div className="card grid gap-5 p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-xl font-semibold text-text-primary">{selectedTemplate.template.name}</h2>
                    <UsageBadge usage={selectedUsage} />
                  </div>
                  <p className="mt-1 font-mono text-xs text-text-tertiary">{selectedTemplate.template.purpose}</p>
                </div>
                <div className="flex flex-wrap gap-2 text-xs">
                  <span className="inline-flex items-center rounded-full border border-border/70 bg-white/70 px-3 py-1 font-mono text-text-secondary">
                    变量 {schemaText(selectedTemplate.template.variables_schema_ref)}
                  </span>
                  <span className="inline-flex items-center rounded-full border border-border/70 bg-white/70 px-3 py-1 font-mono text-text-secondary">
                    输出 {schemaText(selectedTemplate.template.output_schema_ref)}
                  </span>
                </div>
              </div>

              {/* 版本状态步进器 */}
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-xs font-semibold text-text-secondary">当前版本状态</span>
                <StatusStepper status={selectedVersion?.status} />
              </div>

              {/* 编辑器 + 变量面板 */}
              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
                <label className="grid gap-2">
                  <span>编辑内容</span>
                  <textarea
                    ref={editorRef}
                    className="font-mono text-sm"
                    rows={16}
                    value={draftContent}
                    onChange={(event) => setDraftContent(event.target.value)}
                  />
                </label>
                <div className="grid content-start gap-4">
                  <div>
                    <p className="mb-2 text-xs font-semibold text-text-secondary">可插入变量</p>
                    <div className="flex flex-wrap gap-2">
                      {variableChips(selectedTemplate).map((name) => (
                        <button
                          className="rounded-full bg-accent/10 px-3 py-1 font-mono text-xs text-accent transition-colors hover:bg-accent/20"
                          type="button"
                          key={name}
                          onClick={() => insertVariable(name)}
                        >
                          {`{${name}}`}
                        </button>
                      ))}
                    </div>
                  </div>
                  <label className="grid gap-1.5">
                    <span>版本说明</span>
                    <textarea
                      className="min-h-[96px]"
                      rows={4}
                      value={changelog}
                      onChange={(event) => setChangelog(event.target.value)}
                      placeholder="本次修改的简要说明（可选）"
                    />
                  </label>
                  <button
                    className="primaryButton"
                    type="button"
                    disabled={!draftContent.trim() || !currentTemplateId || createVersion.isPending}
                    onClick={() => createVersion.mutate()}
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    <span>保存草稿</span>
                  </button>
                </div>
              </div>
            </div>

            {/* 版本 diff + 绑定管理 */}
            <div className="grid gap-5 xl:grid-cols-2">
              <div className="card grid content-start gap-4 p-5">
                <div className="flex items-center gap-2">
                  <GitCompare className="h-4 w-4 text-accent" />
                  <h3 className="font-semibold text-text-primary">版本对比</h3>
                </div>
                <label className="grid gap-1.5">
                  <span>对比版本（相对已发布版本）</span>
                  <select value={selectedVersionId} onChange={(event) => setSelectedVersionId(event.target.value)}>
                    {versionItems.map((item) => (
                      <option key={item.version.id} value={item.version.id}>
                        {item.version.id} · {statusLabel[item.version.status] ?? item.version.status}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="max-h-[340px] min-h-[260px] overflow-auto rounded-2xl border border-border/70 bg-[#111511] p-3 font-mono text-xs text-white">
                  {rows.length > 0 ? (
                    rows.map((row, index) => (
                      <p
                        key={`${row.kind}-${index}`}
                        className={row.kind === "add" ? "text-status-success" : row.kind === "remove" ? "text-status-error" : "text-white/70"}
                      >
                        {row.kind === "add" ? "+ " : row.kind === "remove" ? "- " : "  "}
                        {row.text}
                      </p>
                    ))
                  ) : (
                    <p className="text-white/60">无差异</p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    className="btn-secondary"
                    type="button"
                    disabled={!selectedVersion || approve.isPending || !["draft", "reviewing"].includes(selectedVersion.status)}
                    onClick={() => selectedVersion && approve.mutate(selectedVersion.id)}
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    <span>审批</span>
                  </button>
                  <button
                    className="btn-secondary"
                    type="button"
                    disabled={!selectedVersion || publish.isPending || selectedVersion.status !== "approved"}
                    onClick={() => selectedVersion && publish.mutate(selectedVersion.id)}
                  >
                    <Send className="h-4 w-4" />
                    <span>发布</span>
                  </button>
                  <button
                    className="btn-secondary"
                    type="button"
                    disabled={!defaultVersion || rollback.isPending}
                    onClick={() => defaultVersion && rollback.mutate(defaultVersion.id)}
                  >
                    <RotateCcw className="h-4 w-4" />
                    <span>恢复默认</span>
                  </button>
                </div>
              </div>

              {/* 绑定管理 */}
              <div className="card grid content-start gap-4 p-5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Link2 className="h-4 w-4 text-accent" />
                    <h3 className="font-semibold text-text-primary">绑定管理</h3>
                    <BindingHint />
                  </div>
                  <UsageBadge usage={selectedUsage} />
                </div>

                {/* 已有绑定列表 */}
                <div className="grid gap-2">
                  {selectedBindings.length > 0 ? (
                    selectedBindings.map((item) => (
                      <div
                        className="flex items-center justify-between gap-3 rounded-2xl border border-border/60 bg-white/55 px-3 py-2.5 transition-colors hover:bg-white/75"
                        key={item.binding.id}
                      >
                        <div className="min-w-0">
                          <p className="flex items-center gap-2 truncate text-sm font-semibold text-text-primary">
                            <span className="truncate">{item.binding.node_id || "全局节点"}</span>
                            <span
                              className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                                item.binding.enabled ? "bg-status-success/15 text-status-success" : "bg-black/5 text-text-tertiary"
                              }`}
                            >
                              {item.binding.enabled ? "已启用" : "已停用"}
                            </span>
                          </p>
                          <p className="mt-0.5 truncate font-mono text-xs text-text-tertiary">
                            {item.binding.case_id || "全局 Case"} · P{item.binding.priority} ·{" "}
                            {item.resolved_version?.id ?? item.binding.prompt_version_id}
                          </p>
                          <p className="mt-0.5 text-[11px] text-text-tertiary">
                            更新于 <TimeText value={item.binding.updated_at} />
                          </p>
                        </div>
                        <button
                          className="icon-button"
                          type="button"
                          onClick={() => patchBinding.mutate(item)}
                          disabled={patchBinding.isPending}
                          aria-label={item.binding.enabled ? "停用绑定" : "启用绑定"}
                          title={item.binding.enabled ? "停用绑定" : "启用绑定"}
                        >
                          {item.binding.enabled ? (
                            <ToggleRight className="h-5 w-5 text-status-success" />
                          ) : (
                            <ToggleLeft className="h-5 w-5" />
                          )}
                        </button>
                      </div>
                    ))
                  ) : (
                    <div className="rounded-2xl border border-dashed border-border/70 bg-white/40 px-4 py-5 text-center text-sm text-text-secondary">
                      该模板暂无绑定 — 未接入生产
                    </div>
                  )}
                </div>

                {/* 新建绑定 */}
                <form
                  className="grid gap-3 border-t border-border/60 pt-4"
                  onSubmit={(event) => {
                    event.preventDefault();
                    createBinding.mutate();
                  }}
                >
                  <p className="text-xs font-semibold text-text-secondary">
                    新建绑定（绑定当前选中版本：{selectedVersion?.id || publishedVersion?.id || "—"}）
                  </p>
                  <div className="twoCol">
                    <label className="grid gap-1.5">
                      <span>节点</span>
                      <input
                        value={bindingForm.node_id}
                        onChange={(event) => setBindingForm((value) => ({ ...value, node_id: event.target.value }))}
                      />
                    </label>
                    <label className="grid gap-1.5">
                      <span>Case ID</span>
                      <input
                        value={bindingForm.case_id}
                        onChange={(event) => setBindingForm((value) => ({ ...value, case_id: event.target.value }))}
                        placeholder="可留空 = 全局"
                      />
                    </label>
                  </div>
                  <label className="grid gap-1.5">
                    <span>优先级</span>
                    <input
                      type="number"
                      value={bindingForm.priority}
                      onChange={(event) => setBindingForm((value) => ({ ...value, priority: Number(event.target.value) }))}
                    />
                  </label>
                  <button
                    className="primaryButton"
                    type="submit"
                    disabled={createBinding.isPending || (!selectedVersion && !publishedVersion)}
                  >
                    <Plus className="h-4 w-4" />
                    <span>新建绑定</span>
                  </button>
                </form>
              </div>
            </div>
          </div>
        ) : null}
      </div>

      {/* 新建模板 Modal */}
      {createOpen ? (
        <Modal title="新建提示词模板" onClose={() => setCreateOpen(false)} size="md">
          <form
            className="formGrid"
            onSubmit={(event) => {
              event.preventDefault();
              createTemplate.mutate();
            }}
          >
            <label className="grid gap-1.5">
              <span>模板名</span>
              <input
                value={templateForm.name}
                onChange={(event) => setTemplateForm((value) => ({ ...value, name: event.target.value }))}
                placeholder="例如：分镜脚本生成"
                required
                autoFocus
              />
            </label>
            <label className="grid gap-1.5">
              <span>能力/用途</span>
              <input
                value={templateForm.purpose}
                onChange={(event) => setTemplateForm((value) => ({ ...value, purpose: event.target.value }))}
                placeholder="例如：prompt.script.storyboard"
                required
              />
              <small className="text-xs font-normal text-text-tertiary">
                以 {activeGroupConfig.prefix} 开头将归入「{activeGroupConfig.label}」分组。
              </small>
            </label>
            <div className="twoCol">
              <label className="grid gap-1.5">
                <span>变量 schema</span>
                <input
                  value={templateForm.variables_schema_id}
                  onChange={(event) => setTemplateForm((value) => ({ ...value, variables_schema_id: event.target.value }))}
                  required
                />
              </label>
              <label className="grid gap-1.5">
                <span>输出 schema</span>
                <input
                  value={templateForm.output_schema_id}
                  onChange={(event) => setTemplateForm((value) => ({ ...value, output_schema_id: event.target.value }))}
                  required
                />
              </label>
            </div>
            <div className="formActions justify-end">
              <button className="btn-secondary" type="button" onClick={() => setCreateOpen(false)}>
                取消
              </button>
              <button className="primaryButton" type="submit" disabled={createDisabled}>
                <Plus className="h-4 w-4" />
                <span>创建模板</span>
              </button>
            </div>
          </form>
        </Modal>
      ) : null}
    </section>
  );
}
