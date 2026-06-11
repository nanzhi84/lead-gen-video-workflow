import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type ApiError } from "../../api/client";
import { EmptyState, ErrorState, LoadingState } from "../../components/State";
import { Modal } from "../../components/Modal";
import { routes } from "../../routes";

type CaseForm = {
  name: string;
  description: string;
  industry: string;
  product: string;
  target_audience: string;
};

const emptyForm: CaseForm = {
  name: "",
  description: "",
  industry: "",
  product: "",
  target_audience: "",
};

export default function CaseListPage() {
  const [search, setSearch] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState<CaseForm>(emptyForm);
  const [formError, setFormError] = useState<unknown>(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const cases = useQuery({
    queryKey: ["cases", search],
    queryFn: () => api.cases.list({ search: search || null, limit: 100 }),
  });
  const createCase = useMutation({
    mutationFn: () =>
      api.cases.create({
        name: form.name.trim(),
        description: form.description.trim() || null,
        industry: form.industry.trim() || null,
        product: form.product.trim() || null,
        target_audience: form.target_audience.trim() || null,
      }),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ["cases"] });
      setModalOpen(false);
      setForm(emptyForm);
      navigate(routes.caseStudio(created.id));
    },
    onError: (error: ApiError) => setFormError(error),
  });

  const items = useMemo(() => cases.data?.items ?? [], [cases.data?.items]);

  return (
    <section className="pageStack">
      <header className="pageHeader">
        <div>
          <h1>Cases</h1>
          <p>{cases.data?.total_hint ?? items.length} 个工作空间，按 Case 管理创作、Runs 和成片。</p>
        </div>
        <button className="primaryButton" type="button" onClick={() => setModalOpen(true)}>
          <Plus size={16} />
          <span>新建 Case</span>
        </button>
      </header>

      <div className="toolbarLine surface">
        <label className="searchBox">
          <Search size={15} />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索 Case 名称"
          />
        </label>
      </div>

      {cases.isLoading ? <LoadingState /> : null}
      {cases.error ? <ErrorState error={cases.error} /> : null}
      {!cases.isLoading && !cases.error && items.length === 0 ? (
        <EmptyState title="暂无 Case" detail="新建一个 Case 后即可进入创作工作台。" />
      ) : null}

      {items.length > 0 ? (
        <div className="dataTable surface">
          <div className="tableRow tableHead caseRow">
            <span>名称</span>
            <span>活跃记忆</span>
            <span>更新</span>
            <span>Owner</span>
          </div>
          {items.map((item) => (
            <Link className="tableRow caseRow rowLink" to={routes.caseStudio(item.id)} key={item.id}>
              <strong>{item.name}</strong>
              <span className="monoNumber">{item.active_memory_count}</span>
              <span>{item.updated_at ? new Date(item.updated_at).toLocaleString() : "-"}</span>
              <span>{item.owner_user_id ?? "-"}</span>
            </Link>
          ))}
        </div>
      ) : null}

      {modalOpen ? (
        <Modal title="新建 Case" onClose={() => setModalOpen(false)}>
          <form
            className="formGrid"
            onSubmit={(event) => {
              event.preventDefault();
              setFormError(null);
              createCase.mutate();
            }}
          >
            <label>
              <span>名称</span>
              <input
                value={form.name}
                onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                required
              />
            </label>
            <label>
              <span>描述</span>
              <textarea
                value={form.description}
                onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
                rows={3}
              />
            </label>
            <div className="twoCol">
              <label>
                <span>行业</span>
                <input
                  value={form.industry}
                  onChange={(event) => setForm((current) => ({ ...current, industry: event.target.value }))}
                />
              </label>
              <label>
                <span>产品</span>
                <input
                  value={form.product}
                  onChange={(event) => setForm((current) => ({ ...current, product: event.target.value }))}
                />
              </label>
            </div>
            <label>
              <span>目标受众</span>
              <input
                value={form.target_audience}
                onChange={(event) => setForm((current) => ({ ...current, target_audience: event.target.value }))}
              />
            </label>
            {formError ? <ErrorState error={formError} /> : null}
            <div className="formActions">
              <button className="ghostButton" type="button" onClick={() => setModalOpen(false)}>
                取消
              </button>
              <button className="primaryButton" type="submit" disabled={createCase.isPending || !form.name.trim()}>
                <Plus size={16} />
                <span>创建</span>
              </button>
            </div>
          </form>
        </Modal>
      ) : null}
    </section>
  );
}
