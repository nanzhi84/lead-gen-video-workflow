import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { api } from "../api/generated";

export default function PublishPage() {
  const queryClient = useQueryClient();
  const videos = useQuery({ queryKey: ["finished", "case_demo"], queryFn: () => api.finishedVideos("case_demo") });
  const packages = useQuery({ queryKey: ["publish-packages"], queryFn: api.publishPackages });
  const batches = useQuery({ queryKey: ["publish-batches"], queryFn: api.publishBatches });
  const createPackage = useMutation({
    mutationFn: () => api.createPublishPackage({ source_finished_video_id: videos.data!.items[0].id, title: "Publish package", description: "" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["publish-packages"] }),
  });
  const createBatch = useMutation({
    mutationFn: async () => {
      const packageId = packages.data!.items[0].id;
      const batch = await api.createPublishBatch({ publish_package_ids: [packageId], platform_targets: ["xiaovmao"] });
      return api.submitPublishBatch(batch.id);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["publish-batches"] }),
  });

  return (
    <section className="page split">
      <div className="panel">
        <header className="toolbar compact">
          <div>
            <h1>Packages</h1>
            <p>{packages.data?.total_hint ?? 0} ready</p>
          </div>
          <button className="primary" onClick={() => createPackage.mutate()} disabled={!videos.data?.items.length}>
            <Send size={17} />
            <span>Create</span>
          </button>
        </header>
        <div className="list">
          {packages.data?.items.map((item) => (
            <div className="listItem" key={item.id}>
              <strong>{item.platform_defaults.title}</strong>
              <span>{item.id}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="panel">
        <header className="toolbar compact">
          <div>
            <h1>Batches</h1>
            <p>{batches.data?.total_hint ?? 0} batches</p>
          </div>
          <button className="primary" onClick={() => createBatch.mutate()} disabled={!packages.data?.items.length}>
            <Send size={17} />
            <span>Submit</span>
          </button>
        </header>
        <div className="list">
          {batches.data?.items.map((batch) => (
            <div className="listItem" key={batch.id}>
              <strong>{batch.status}</strong>
              <span>{(batch.items ?? []).length} item(s)</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
