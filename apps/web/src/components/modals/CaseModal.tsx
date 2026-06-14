import { Plus, Save } from "lucide-react";
import { useState } from "react";
import type { CaseDetail, CreateCaseRequest, PatchCaseRequest } from "../../api/client";
import { Modal } from "../Modal";
import { ErrorState } from "../State";

export type CaseModalMode = "create" | "edit";

type CaseFormState = {
  name: string;
  description: string;
  industry: string;
  product: string;
  target_audience: string;
  key_selling_points: string;
  ip_persona: string;
  brand_voice: string;
  strategy_tags: string;
  brand_keywords: string;
  competitor_names: string;
};

const emptyForm: CaseFormState = {
  name: "",
  description: "",
  industry: "",
  product: "",
  target_audience: "",
  key_selling_points: "",
  ip_persona: "",
  brand_voice: "",
  strategy_tags: "",
  brand_keywords: "",
  competitor_names: "",
};

// List profile fields are edited as one-per-line text. Newlines and commas both split.
export function parseList(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

export function joinList(value: readonly string[] | null | undefined): string {
  return (value ?? []).join("\n");
}

function formFromCase(detail: CaseDetail): CaseFormState {
  return {
    name: detail.name ?? "",
    description: detail.description ?? "",
    industry: detail.industry ?? "",
    product: detail.product ?? "",
    target_audience: detail.target_audience ?? "",
    key_selling_points: joinList(detail.key_selling_points),
    ip_persona: detail.ip_persona ?? "",
    brand_voice: detail.brand_voice ?? "",
    strategy_tags: joinList(detail.strategy_tags),
    brand_keywords: joinList(detail.brand_keywords),
    competitor_names: joinList(detail.competitor_names),
  };
}

export function buildCreatePayload(form: CaseFormState): CreateCaseRequest {
  return {
    name: form.name.trim(),
    description: form.description.trim() || null,
    industry: form.industry.trim() || null,
    product: form.product.trim() || null,
    target_audience: form.target_audience.trim() || null,
    key_selling_points: parseList(form.key_selling_points),
    ip_persona: form.ip_persona.trim() || null,
    brand_voice: form.brand_voice.trim() || null,
    strategy_tags: parseList(form.strategy_tags),
    brand_keywords: parseList(form.brand_keywords),
    competitor_names: parseList(form.competitor_names),
  };
}

export function buildPatchPayload(form: CaseFormState): PatchCaseRequest {
  return {
    name: form.name.trim(),
    description: form.description.trim() || null,
    industry: form.industry.trim() || null,
    product: form.product.trim() || null,
    target_audience: form.target_audience.trim() || null,
    key_selling_points: parseList(form.key_selling_points),
    ip_persona: form.ip_persona.trim() || null,
    brand_voice: form.brand_voice.trim() || null,
    strategy_tags: parseList(form.strategy_tags),
    brand_keywords: parseList(form.brand_keywords),
    competitor_names: parseList(form.competitor_names),
  };
}

export function CaseModal({
  mode,
  initial,
  isSaving,
  error,
  onClose,
  onCreate,
  onPatch,
}: {
  mode: CaseModalMode;
  initial?: CaseDetail | null;
  isSaving: boolean;
  error?: unknown;
  onClose: () => void;
  onCreate?: (payload: CreateCaseRequest) => void;
  onPatch?: (payload: PatchCaseRequest) => void;
}) {
  const [form, setForm] = useState<CaseFormState>(() =>
    mode === "edit" && initial ? formFromCase(initial) : emptyForm,
  );

  function update<Key extends keyof CaseFormState>(key: Key, value: CaseFormState[Key]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (mode === "create") onCreate?.(buildCreatePayload(form));
    else onPatch?.(buildPatchPayload(form));
  }

  return (
    <Modal title={mode === "create" ? "新建案例" : "编辑案例"} onClose={onClose} size="lg">
      <form className="formGrid" onSubmit={handleSubmit}>
        <label>
          <span>名称</span>
          <input value={form.name} onChange={(event) => update("name", event.target.value)} required />
        </label>
        <label>
          <span>描述</span>
          <textarea value={form.description} onChange={(event) => update("description", event.target.value)} rows={3} />
        </label>
        <div className="twoCol">
          <label>
            <span>行业</span>
            <input value={form.industry} onChange={(event) => update("industry", event.target.value)} />
          </label>
          <label>
            <span>产品</span>
            <input value={form.product} onChange={(event) => update("product", event.target.value)} />
          </label>
        </div>
        <label>
          <span>目标受众</span>
          <input value={form.target_audience} onChange={(event) => update("target_audience", event.target.value)} />
        </label>

        <div className="twoCol">
          <label>
            <span>IP 人设</span>
            <input value={form.ip_persona} onChange={(event) => update("ip_persona", event.target.value)} />
          </label>
          <label>
            <span>品牌声音</span>
            <input value={form.brand_voice} onChange={(event) => update("brand_voice", event.target.value)} />
          </label>
        </div>
        <label>
          <span>核心卖点（每行一个）</span>
          <textarea
            value={form.key_selling_points}
            onChange={(event) => update("key_selling_points", event.target.value)}
            rows={3}
            placeholder="每行一个卖点"
          />
        </label>
        <div className="twoCol">
          <label>
            <span>策略标签（每行一个）</span>
            <textarea
              value={form.strategy_tags}
              onChange={(event) => update("strategy_tags", event.target.value)}
              rows={2}
            />
          </label>
          <label>
            <span>品牌关键词（每行一个）</span>
            <textarea
              value={form.brand_keywords}
              onChange={(event) => update("brand_keywords", event.target.value)}
              rows={2}
            />
          </label>
        </div>
        <label>
          <span>竞品名称（每行一个）</span>
          <textarea
            value={form.competitor_names}
            onChange={(event) => update("competitor_names", event.target.value)}
            rows={2}
          />
        </label>

        {error ? <ErrorState error={error} /> : null}
        <div className="formActions">
          <button className="ghostButton" type="button" onClick={onClose}>
            取消
          </button>
          <button className="primaryButton" type="submit" disabled={isSaving || !form.name.trim()}>
            {mode === "create" ? <Plus size={16} /> : <Save size={16} />}
            <span>{mode === "create" ? "创建" : "保存"}</span>
          </button>
        </div>
      </form>
    </Modal>
  );
}
