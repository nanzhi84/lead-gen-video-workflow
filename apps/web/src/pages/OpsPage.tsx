import { useQuery } from "@tanstack/react-query";
import { api } from "../api/generated";

export default function OpsPage({ mode = "ops" }: { mode?: "ops" | "runs" }) {
  const dashboard = useQuery({ queryKey: ["ops-dashboard"], queryFn: api.opsDashboard });
  const data = dashboard.data;
  return (
    <section className="page">
      <header className="toolbar">
        <div>
          <h1>{mode === "runs" ? "Runs" : "Ops"}</h1>
          <p>{data?.yield_funnel.events.length ?? 0} events</p>
        </div>
      </header>
      <div className="metricGrid">
        <div><b>{data?.usage.invocations ?? 0}</b><span>provider calls</span></div>
        <div><b>{data?.usage.estimated_cost.amount ?? 0}</b><span>cost</span></div>
        <div><b>{Math.round((data?.yield_funnel.true_yield_rate ?? 0) * 100)}%</b><span>true yield</span></div>
        <div><b>{data?.alerts.length ?? 0}</b><span>alerts</span></div>
      </div>
      <div className="table">
        <div className="row head">
          <span>Event</span>
          <span>ID</span>
        </div>
        {data?.yield_funnel.events.map((event) => (
          <div className="row two" key={event.id}>
            <strong>{event.event_name}</strong>
            <span>{event.id}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

