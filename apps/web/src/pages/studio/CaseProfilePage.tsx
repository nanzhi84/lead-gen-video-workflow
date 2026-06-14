import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type ApiError, type CaseDetail, type PatchCaseRequest } from "../../api/client";
import { joinList, parseList } from "../../components/modals/CaseModal";
import { EmptyState, ErrorState, LoadingState } from "../../components/State";
import { StudioTabs } from "../../components/StudioTabs";
import { useToast } from "../../components/Toast";

type ProfileForm = {
  industry: string;
  key_selling_points: string;
  ip_persona: string;
  brand_voice: string;
  strategy_tags: string;
  brand_keywords: string;
  competitor_names: string;
};

function formFromCase(detail: CaseDetail): ProfileForm {
  return {
    industry: detail.industry ?? "",
    key_selling_points: joinList(detail.key_selling_points),
    ip_persona: detail.ip_persona ?? "",
    brand_voice: detail.brand_voice ?? "",
    strategy_tags: joinList(detail.strategy_tags),
    brand_keywords: joinList(detail.brand_keywords),
    competitor_names: joinList(detail.competitor_names),
  };
}

function buildPayload(form: ProfileForm): PatchCaseRequest {
  return {
    industry: form.industry.trim() || null,
    key_selling_points: parseList(form.key_selling_points),
    ip_persona: form.ip_persona.trim() || null,
    brand_voice: form.brand_voice.trim() || null,
    strategy_tags: parseList(form.strategy_tags),
    brand_keywords: parseList(form.brand_keywords),
    competitor_names: parseList(form.competitor_names),
  };
}

const emptyForm: ProfileForm = {
  industry: "",
  key_selling_points: "",
  ip_persona: "",
  brand_voice: "",
  strategy_tags: "",
  brand_keywords: "",
  competitor_names: "",
};

export default function CaseProfilePage() {
  const { caseId = "" } = useParams();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState<ProfileForm>(emptyForm);
  const [formError, setFormError] = useState<unknown>(null);

  const caseDetail = useQuery({
    queryKey: ["case", caseId],
    queryFn: () => api.cases.detail(caseId),
    enabled: Boolean(caseId),
  });

  useEffect(() => {
    if (caseDetail.data) setForm(formFromCase(caseDetail.data));
  }, [caseDetail.data]);

  const save = useMutation({
    mutationFn: () => api.cases.patch(caseId, buildPayload(form)),
    onSuccess: async (updated) => {
      setForm(formFromCase(updated));
      await queryClient.invalidateQueries({ queryKey: ["case", caseId] });
      await queryClient.invalidateQueries({ queryKey: ["cases"] });
      toast.success("案例画像已保存", updated.name);
    },
    onError: (error: ApiError) => setFormError(error),
  });

  function update<Key extends keyof ProfileForm>(key: Key, value: ProfileForm[Key]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  if (!caseId) return <EmptyState title="未选择案例" detail="请从案例中心进入工作台。" />;

  return (
    <section className="pageStack">
      <header className="pageHeader">
        <div>
          <h1>案例画像</h1>
          <p>{caseDetail.data?.name ?? "维护行业、卖点、人设与品牌信息，用于脚本生成和智能体推理。"}</p>
        </div>
      </header>
      <StudioTabs caseId={caseId} />
      {caseDetail.error ? <ErrorState error={caseDetail.error} /> : null}
      {caseDetail.isLoading ? <LoadingState label="加载案例画像" /> : null}

      {caseDetail.data ? (
        <form
          className="card formGrid"
          onSubmit={(event) => {
            event.preventDefault();
            setFormError(null);
            save.mutate();
          }}
        >
          <label>
            <span>行业</span>
            <input value={form.industry} onChange={(event) => update("industry", event.target.value)} />
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
              rows={4}
              placeholder="每行一个卖点"
            />
          </label>
          <div className="twoCol">
            <label>
              <span>策略标签（每行一个）</span>
              <textarea
                value={form.strategy_tags}
                onChange={(event) => update("strategy_tags", event.target.value)}
                rows={3}
              />
            </label>
            <label>
              <span>品牌关键词（每行一个）</span>
              <textarea
                value={form.brand_keywords}
                onChange={(event) => update("brand_keywords", event.target.value)}
                rows={3}
              />
            </label>
          </div>
          <label>
            <span>竞品名称（每行一个）</span>
            <textarea
              value={form.competitor_names}
              onChange={(event) => update("competitor_names", event.target.value)}
              rows={3}
            />
          </label>
          {formError ? <ErrorState error={formError} /> : null}
          <div className="formActions">
            <button
              className="ghostButton"
              type="button"
              onClick={() => caseDetail.data && setForm(formFromCase(caseDetail.data))}
              disabled={save.isPending}
            >
              重置
            </button>
            <button className="primaryButton" type="submit" disabled={save.isPending}>
              <Save size={16} />
              <span>保存画像</span>
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
