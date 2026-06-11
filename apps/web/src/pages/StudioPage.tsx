import { useMutation, useQuery } from "@tanstack/react-query";
import { Play, RotateCw } from "lucide-react";
import { useState } from "react";
import { api, WorkflowRun } from "../api/generated";

export default function StudioPage() {
  const [script, setScript] = useState("先指出内容生产低效。再展示 Case Memory 如何复用经验。最后推动发布复盘。");
  const [lastRun, setLastRun] = useState<WorkflowRun | null>(null);
  const caseDetail = useQuery({ queryKey: ["case", "case_demo"], queryFn: () => api.caseDetail("case_demo") });
  const videos = useQuery({ queryKey: ["finished", "case_demo"], queryFn: () => api.finishedVideos("case_demo") });
  const report = useQuery({
    queryKey: ["run-report", lastRun?.id],
    queryFn: () => api.runReport(lastRun!.id),
    enabled: Boolean(lastRun?.id),
  });
  const createJob = useMutation({
    mutationFn: () =>
      api.createVideoJob({
        case_id: "case_demo",
        title: "Studio draft",
        script,
        voice: { voice_id: "voice_sandbox" },
        portrait: { required: true },
        broll: { enabled: true, max_inserts: 2 },
        bgm: { enabled: false },
        subtitles: { enabled: true },
      }),
    onSuccess: (data) => {
      setLastRun(data.initial_run ?? null);
      videos.refetch();
    },
  });

  return (
    <section className="page split">
      <div className="panel">
        <header className="toolbar compact">
          <div>
            <h1>{caseDetail.data?.name ?? "Studio"}</h1>
            <p>{caseDetail.data?.product ?? "case_demo"}</p>
          </div>
          <button className="primary" onClick={() => createJob.mutate()} title="Start run">
            {createJob.isPending ? <RotateCw size={17} className="spin" /> : <Play size={17} />}
            <span>Run</span>
          </button>
        </header>
        <textarea value={script} onChange={(event) => setScript(event.target.value)} />
        {lastRun && (
          <div className={`status ${lastRun.status}`}>
            <span>{lastRun.status}</span>
            <span>{lastRun.id}</span>
          </div>
        )}
        {report.data && (
          <div className="metricGrid">
            <div><b>{report.data.public_report.status}</b><span>status</span></div>
            <div><b>{report.data.public_report.degradations.length}</b><span>degrade</span></div>
            <div><b>{report.data.public_report.warnings.length}</b><span>warnings</span></div>
          </div>
        )}
      </div>
      <div className="panel">
        <h2>Finished Videos</h2>
        <div className="list">
          {videos.data?.items.map((video) => (
            <div className="listItem" key={video.id}>
              <strong>{video.title}</strong>
              <span>{video.duration_sec.toFixed(1)}s · {video.qc_status}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

