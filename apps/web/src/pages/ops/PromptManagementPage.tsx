import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, GitCompare, Plus, RotateCcw, Send, ToggleLeft, ToggleRight } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type ApiError, type PromptBindingView } from "../../api/client";
import { EmptyState, ErrorState, LoadingState } from "../../components/State";
import { useToast } from "../../components/Toast";
import { TimeText } from "../../components/TimeText";
import {
  bindingSummary,
  diffRows,
  emptyBinding,
  emptyTemplate,
  flow,
  promptGroups,
  schemaText,
  statusLabel,
  variableChips,
  type BindingForm,
  type PromptGroupKey,
  type TemplateForm,
} from "./promptManagementUtils";

export default function PromptManagementPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const [activeGroup, setActiveGroup] = useState<PromptGroupKey>("script");
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [templateForm, setTemplateForm] = useState<TemplateForm>(emptyTemplate);
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

  return (
    <section className="pageStack">
      <header className="pageHeader">
        <div>
          <h1>提示词</h1>
          <p>按生产用途管理已发布提示词，生产环境读取已发布版本。</p>
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

      <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="grid content-start gap-3">
          <form
            className="card formGrid p-4"
            onSubmit={(event) => {
              event.preventDefault();
              createTemplate.mutate();
            }}
          >
            <label><span>模板名</span><input value={templateForm.name} onChange={(event) => setTemplateForm((value) => ({ ...value, name: event.target.value }))} required /></label>
            <label><span>能力/用途</span><input value={templateForm.purpose} onChange={(event) => setTemplateForm((value) => ({ ...value, purpose: event.target.value }))} required /></label>
            <label><span>变量 schema</span><input value={templateForm.variables_schema_id} onChange={(event) => setTemplateForm((value) => ({ ...value, variables_schema_id: event.target.value }))} required /></label>
            <label><span>输出 schema</span><input value={templateForm.output_schema_id} onChange={(event) => setTemplateForm((value) => ({ ...value, output_schema_id: event.target.value }))} required /></label>
            <button className="primaryButton" type="submit" disabled={createTemplate.isPending || !templateForm.name.trim() || !templateForm.purpose.trim()}>
              <Plus className="h-4 w-4" />
              <span>新建模板</span>
            </button>
          </form>

          <div className="card p-0">
            <div className="divide-y divide-border/60">
            {groupedTemplateItems.map((item) => (
              <button
                className={`block w-full px-4 py-3 text-left transition-colors hover:bg-hover ${selectedTemplate?.template.id === item.template.id ? "bg-accent/10" : ""}`}
                key={item.template.id}
                type="button"
                onClick={() => setSelectedTemplateId(item.template.id)}
              >
                <span className="block truncate font-semibold text-text-primary">{item.template.name}</span>
                <span className="mt-1 block truncate text-xs text-text-tertiary">{item.template.purpose}</span>
                <span className="mt-2 block truncate text-xs text-text-secondary">{bindingSummary(bindingItems, item.template.id)}</span>
                <span className="mt-3 inline-flex rounded-full bg-white/70 px-2.5 py-1 text-xs text-text-secondary">{statusLabel[item.template.status] ?? item.template.status}</span>
              </button>
            ))}
            {groupedTemplateItems.length === 0 ? (
              <div className="px-4 py-6 text-sm text-text-secondary">当前分组暂无模板。</div>
            ) : null}
            </div>
          </div>
        </aside>

        {selectedTemplate ? (
          <div className="grid gap-4">
            <div className="card grid gap-4 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-xl font-semibold text-text-primary">{selectedTemplate.template.name}</h2>
                  <p className="text-sm text-text-secondary">{selectedTemplate.template.purpose}</p>
                </div>
                <div className="flex flex-wrap gap-2 text-xs">
                  <span className="rounded-full border border-border/70 bg-white/70 px-3 py-1">{schemaText(selectedTemplate.template.variables_schema_ref)}</span>
                  <span className="rounded-full border border-border/70 bg-white/70 px-3 py-1">{schemaText(selectedTemplate.template.output_schema_ref)}</span>
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                {flow.map((step) => (
                  <span key={step} className={`rounded-full px-3 py-1 text-xs ${selectedVersion?.status === step ? "bg-accent text-[#1b1d1a]" : "bg-white/70 text-text-secondary"}`}>
                    {statusLabel[step]}
                  </span>
                ))}
              </div>

              <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_280px]">
                <label className="grid gap-2">
                  <span>编辑内容</span>
                  <textarea ref={editorRef} className="font-mono text-sm" rows={14} value={draftContent} onChange={(event) => setDraftContent(event.target.value)} />
                </label>
                <div className="grid content-start gap-3">
                  <div className="border-t border-border/60 pt-3">
                    <p className="mb-2 text-xs font-semibold text-text-secondary">变量</p>
                    <div className="flex flex-wrap gap-2">
                      {variableChips(selectedTemplate).map((name) => (
                        <button className="rounded-full bg-accent/10 px-3 py-1 text-xs text-accent hover:bg-accent/15" type="button" key={name} onClick={() => insertVariable(name)}>
                          {`{${name}}`}
                        </button>
                      ))}
                    </div>
                  </div>
                  <label>
                    <span>版本说明</span>
                    <textarea rows={4} value={changelog} onChange={(event) => setChangelog(event.target.value)} />
                  </label>
                  <button className="primaryButton" type="button" disabled={!draftContent.trim() || !currentTemplateId || createVersion.isPending} onClick={() => createVersion.mutate()}>
                    <CheckCircle2 className="h-4 w-4" />
                    <span>保存草稿</span>
                  </button>
                </div>
              </div>
            </div>

            <div className="grid gap-4 xl:grid-cols-2">
              <div className="card grid gap-3 p-4">
                <div className="flex items-center gap-2">
                  <GitCompare className="h-4 w-4 text-accent" />
                  <h3 className="font-semibold text-text-primary">版本 diff</h3>
                </div>
                <select value={selectedVersionId} onChange={(event) => setSelectedVersionId(event.target.value)}>
                  {versionItems.map((item) => (
                    <option key={item.version.id} value={item.version.id}>
                      {item.version.id} · {statusLabel[item.version.status] ?? item.version.status}
                    </option>
                  ))}
                </select>
                <div className="min-h-[360px] max-h-[360px] overflow-auto rounded-2xl border border-border/70 bg-[#111511] p-3 font-mono text-xs text-white">
                  {rows.length > 0 ? rows.map((row, index) => (
                    <p key={`${row.kind}-${index}`} className={row.kind === "add" ? "text-status-success" : row.kind === "remove" ? "text-status-error" : "text-white/70"}>
                      {row.kind === "add" ? "+ " : row.kind === "remove" ? "- " : "  "}{row.text}
                    </p>
                  )) : <p className="text-white/60">无差异</p>}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button className="btn-secondary" type="button" disabled={!selectedVersion || approve.isPending || !["draft", "reviewing"].includes(selectedVersion.status)} onClick={() => selectedVersion && approve.mutate(selectedVersion.id)}>
                    <CheckCircle2 className="h-4 w-4" />
                    <span>审批</span>
                  </button>
                  <button className="btn-secondary" type="button" disabled={!selectedVersion || publish.isPending || selectedVersion.status !== "approved"} onClick={() => selectedVersion && publish.mutate(selectedVersion.id)}>
                    <Send className="h-4 w-4" />
                    <span>发布</span>
                  </button>
                  <button className="btn-secondary" type="button" disabled={!defaultVersion || rollback.isPending} onClick={() => defaultVersion && rollback.mutate(defaultVersion.id)}>
                    <RotateCcw className="h-4 w-4" />
                    <span>恢复默认</span>
                  </button>
                </div>
              </div>

              <div className="card grid gap-3 p-4">
                <h3 className="font-semibold text-text-primary">绑定</h3>
                <form className="grid gap-3" onSubmit={(event) => { event.preventDefault(); createBinding.mutate(); }}>
                  <div className="twoCol">
                    <label>
                      <span>Case ID</span>
                      <input value={bindingForm.case_id} onChange={(event) => setBindingForm((value) => ({ ...value, case_id: event.target.value }))} placeholder="可留空" />
                    </label>
                    <label>
                      <span>节点</span>
                      <input value={bindingForm.node_id} onChange={(event) => setBindingForm((value) => ({ ...value, node_id: event.target.value }))} />
                    </label>
                  </div>
                  <label>
                    <span>优先级</span>
                    <input type="number" value={bindingForm.priority} onChange={(event) => setBindingForm((value) => ({ ...value, priority: Number(event.target.value) }))} />
                  </label>
                  <button className="primaryButton" type="submit" disabled={!selectedVersion && !publishedVersion}>
                    <Plus className="h-4 w-4" />
                    <span>新建绑定</span>
                  </button>
                </form>
                <div className="divide-y divide-border/60">
                  {selectedBindings.map((item) => (
                    <div className="-mx-2 px-2 py-3 first:pt-0 last:pb-0 transition-colors hover:bg-hover" key={item.binding.id}>
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-text-primary">{item.binding.node_id || "全局节点"} · {item.binding.case_id || "全局 Case"}</p>
                          <p className="text-xs text-text-tertiary">
                            P{item.binding.priority} · {item.binding.enabled ? "启用" : "停用"} · {item.resolved_version?.id ?? item.binding.prompt_version_id} · <TimeText value={item.binding.updated_at} />
                          </p>
                        </div>
                        <button className="icon-button" type="button" onClick={() => patchBinding.mutate(item)} aria-label="切换绑定">
                          {item.binding.enabled ? <ToggleRight className="h-4 w-4" /> : <ToggleLeft className="h-4 w-4" />}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
