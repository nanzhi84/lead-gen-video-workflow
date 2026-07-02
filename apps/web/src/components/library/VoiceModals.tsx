import { CheckCircle2, Loader2, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CaseListItem, type VoiceProfile } from "../../api/client";
import { useUpload } from "../../hooks/useUpload";
import { DropZone } from "../ui/DropZone";
import { Modal } from "../ui/Modal";
import { useToast } from "../ui/Toast";
import { uploadStageLabel, vendorLabel, VOICE_UPLOAD_ACCEPT } from "./libraryModel";

type CaseBindingPickerProps = {
  cases: CaseListItem[];
  selectedCaseIds: string[];
  onChange: (caseIds: string[]) => void;
  disabled?: boolean;
};

function CaseBindingPicker({ cases, selectedCaseIds, onChange, disabled = false }: CaseBindingPickerProps) {
  const selected = new Set(selectedCaseIds);

  function toggle(caseId: string) {
    if (selected.has(caseId)) {
      onChange(selectedCaseIds.filter((id) => id !== caseId));
      return;
    }
    onChange([...selectedCaseIds, caseId]);
  }

  return (
    <fieldset className="grid gap-2">
      <legend className="w-full">
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm font-semibold text-text-primary">绑定案例</span>
          <span className="text-xs font-normal text-text-tertiary">可多选 · 已选 {selectedCaseIds.length} 个</span>
        </div>
      </legend>
      {cases.length === 0 ? (
        <div className="stateBox muted">
          <span>暂无可绑定案例</span>
        </div>
      ) : (
        <div className="grid max-h-56 gap-2 overflow-y-auto rounded-2xl border border-border/80 bg-white/55 p-2">
          {cases.map((item) => (
            <label
              key={item.id}
              className={`flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2 text-sm transition ${
                selected.has(item.id)
                  ? "border-accent/20 bg-accent/10"
                  : "border-transparent hover:bg-white/75"
              }`}
            >
              <input
                type="checkbox"
                checked={selected.has(item.id)}
                disabled={disabled}
                onChange={() => toggle(item.id)}
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium text-text-primary">{item.name}</span>
                {item.industry ? <span className="block truncate text-xs text-text-tertiary">{item.industry}</span> : null}
              </span>
            </label>
          ))}
        </div>
      )}
    </fieldset>
  );
}

export function CloneVoiceModal({
  isOpen,
  onClose,
  cases,
}: {
  isOpen: boolean;
  onClose: () => void;
  cases: CaseListItem[];
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const upload = useUpload();
  const [name, setName] = useState("");
  const [providerProfileId, setProviderProfileId] = useState("");
  const [caseIds, setCaseIds] = useState<string[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const profilesQuery = useQuery({
    queryKey: ["providers", "profiles", "tts.speech"],
    queryFn: () => api.providers.profiles({ capability: "tts.speech" }),
  });

  const cloneMutation = useMutation({
    mutationFn: async () => {
      const file = files[0];
      if (!name.trim()) throw new Error("请输入音色名称");
      if (!file) throw new Error("请上传一段参考音频");
      const result = await upload.uploadFile({ file, kind: "voice_reference" });
      return api.voices.clone({
        display_name: name.trim(),
        reference_upload_session_id: result.upload_session.id,
        provider_profile_id: providerProfileId.trim() || null,
        case_ids: caseIds,
      });
    },
    onSuccess: async (voice) => {
      await queryClient.invalidateQueries({ queryKey: ["library", "voices"] });
      await queryClient.invalidateQueries({ queryKey: ["voices"] });
      await queryClient.invalidateQueries({ queryKey: ["cases"] });
      toast.success("音色克隆已提交", `新音色：${voice.display_name}`);
      setName("");
      setProviderProfileId("");
      setCaseIds([]);
      setFiles([]);
      upload.reset();
      onClose();
    },
    onError: (err) => {
      const message = err instanceof Error ? err.message : "音色克隆失败";
      setError(message);
      toast.error("音色克隆失败", message);
    },
  });

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="克隆音色" size="lg">
      <form
        className="grid gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          setError(null);
          cloneMutation.mutate();
        }}
      >
        <div className="grid gap-3 md:grid-cols-2">
          <label>
            <span>音色名称</span>
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：温柔讲解女声" />
          </label>
          <label>
            <span>厂商（TTS 供应商）</span>
            <select value={providerProfileId} onChange={(event) => setProviderProfileId(event.target.value)}>
              <option value="">默认（自动选择）</option>
              {(profilesQuery.data?.items ?? []).map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {vendorLabel((profile.provider_id ?? "").split(".")[0])} · {profile.display_name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <CaseBindingPicker cases={cases} selectedCaseIds={caseIds} onChange={setCaseIds} disabled={cloneMutation.isPending} />
        <DropZone accept={VOICE_UPLOAD_ACCEPT} maxSize={80} multiple={false} onFilesDrop={(nextFiles) => setFiles(nextFiles)} label="上传参考音频" />
        {upload.status !== "idle" ? (
          <div className="rounded-2xl border border-border/80 bg-white/65 p-3">
            <div className="flex items-center justify-between gap-3 text-sm text-text-secondary">
              <span>上传阶段：{uploadStageLabel(upload.status)}</span>
              <span>{upload.progress}%</span>
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-border/70">
              <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${upload.progress}%` }} />
            </div>
          </div>
        ) : null}
        {error ? <p className="text-sm text-status-error">{error}</p> : null}
        <div className="flex justify-end gap-3 border-t border-border/70 pt-4">
          <button className="btn-secondary" type="button" onClick={onClose} disabled={cloneMutation.isPending}>
            取消
          </button>
          <button className="btn-primary" type="submit" disabled={cloneMutation.isPending || !name.trim() || files.length === 0}>
            {cloneMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            <span>{cloneMutation.isPending ? "提交中" : "创建克隆音色"}</span>
          </button>
        </div>
      </form>
    </Modal>
  );
}

type EditVoiceModalProps = {
  voice: VoiceProfile;
  isOpen: boolean;
  isLoading: boolean;
  onClose: () => void;
  cases: CaseListItem[];
  onSubmit: (displayName: string, enabled: boolean, caseIds: string[]) => void;
};

export function EditVoiceModal({ voice, isOpen, isLoading, onClose, cases, onSubmit }: EditVoiceModalProps) {
  const [displayName, setDisplayName] = useState(voice.display_name);
  const [enabled, setEnabled] = useState(voice.enabled);
  const [caseIds, setCaseIds] = useState<string[]>(voice.case_ids ?? []);

  useEffect(() => {
    setDisplayName(voice.display_name);
    setEnabled(voice.enabled);
    setCaseIds(voice.case_ids ?? []);
  }, [voice]);

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="编辑音色" size="md">
      <form
        className="grid gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit(displayName.trim(), enabled, caseIds);
        }}
      >
        <label>
          <span>音色名称</span>
          <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} disabled={isLoading} />
        </label>
        <label className="flex cursor-pointer grid-cols-[auto_minmax(0,1fr)] items-center gap-3 rounded-2xl border border-border/80 bg-white/65 p-3">
          <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} disabled={isLoading} />
          <span>
            <span className="block text-sm font-semibold text-text-primary">在创作页启用</span>
            <span className="mt-1 block text-xs font-normal text-text-secondary">停用后不会出现在新任务可选音色中。</span>
          </span>
        </label>
        <CaseBindingPicker cases={cases} selectedCaseIds={caseIds} onChange={setCaseIds} disabled={isLoading} />
        <div className="rounded-2xl border border-status-warning/20 bg-status-warning/10 p-3 text-xs leading-5 text-status-warning">
          修改名称会影响后续选择展示；停用只影响新建任务，不改写历史任务记录。
        </div>
        <div className="flex justify-end gap-3 border-t border-border/70 pt-4">
          <button className="btn-secondary" type="button" onClick={onClose} disabled={isLoading}>
            取消
          </button>
          <button className="btn-primary" type="submit" disabled={isLoading || !displayName.trim()}>
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
            <span>{isLoading ? "保存中" : "保存"}</span>
          </button>
        </div>
      </form>
    </Modal>
  );
}
