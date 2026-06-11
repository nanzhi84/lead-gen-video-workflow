import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { api } from "../api/generated";

export default function CasesPage() {
  const queryClient = useQueryClient();
  const cases = useQuery({ queryKey: ["cases"], queryFn: api.cases });
  const createCase = useMutation({
    mutationFn: () => api.createCase({ name: `Case ${new Date().toLocaleTimeString()}` }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["cases"] }),
  });

  return (
    <section className="page">
      <header className="toolbar">
        <div>
          <h1>Cases</h1>
          <p>{cases.data?.total_hint ?? 0} active workspaces</p>
        </div>
        <button className="primary" onClick={() => createCase.mutate()} title="Create case">
          <Plus size={17} />
          <span>New</span>
        </button>
      </header>
      <div className="table">
        <div className="row head">
          <span>Name</span>
          <span>Owner</span>
          <span>Memory</span>
          <span>Updated</span>
        </div>
        {cases.data?.items.map((item) => (
          <div className="row" key={item.id}>
            <strong>{item.name}</strong>
            <span>{item.owner_user_id ?? "-"}</span>
            <span>{item.active_memory_count}</span>
            <span>{item.updated_at ? new Date(item.updated_at).toLocaleString() : "-"}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
