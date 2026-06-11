import { useQuery } from "@tanstack/react-query";
import { api } from "../api/generated";

export default function AssetsPage() {
  const assets = useQuery({ queryKey: ["assets"], queryFn: api.assets });
  return (
    <section className="page">
      <header className="toolbar">
        <div>
          <h1>Assets</h1>
          <p>{assets.data?.total_hint ?? 0} indexed items</p>
        </div>
      </header>
      <div className="table">
        <div className="row head">
          <span>Title</span>
          <span>Kind</span>
          <span>Annotation</span>
          <span>Usable</span>
        </div>
        {assets.data?.items.map(({ asset }) => (
          <div className="row" key={asset.id}>
            <strong>{asset.title}</strong>
            <span>{asset.kind}</span>
            <span>{asset.annotation_status}</span>
            <span>{asset.usable ? "yes" : "no"}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

