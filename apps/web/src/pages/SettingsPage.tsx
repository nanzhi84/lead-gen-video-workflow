import { useQuery } from "@tanstack/react-query";
import { api } from "../api/generated";

export default function SettingsPage() {
  const profiles = useQuery({ queryKey: ["provider-profiles"], queryFn: api.providerProfiles });
  const balances = useQuery({ queryKey: ["provider-balances"], queryFn: api.providerBalances });
  return (
    <section className="page split">
      <div className="panel">
        <h1>Providers</h1>
        <div className="list">
          {profiles.data?.items.map((profile) => (
            <div className="listItem" key={profile.id}>
              <strong>{profile.display_name}</strong>
              <span>{profile.capability} · {profile.enabled ? "enabled" : "disabled"}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="panel">
        <h1>Balances</h1>
        <div className="list">
          {balances.data?.items.map((item) => (
            <div className="listItem" key={item.provider_id}>
              <strong>{item.provider_id}</strong>
              <span>{item.status} · {item.quota_remaining ?? "-"}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

