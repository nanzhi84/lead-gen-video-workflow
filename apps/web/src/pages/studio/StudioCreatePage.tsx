import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2, Play } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type ApiError } from "../../api/client";
import { ErrorState, LoadingState } from "../../components/State";
import { StudioTabs } from "../../components/StudioTabs";
import { routes } from "../../routes";

type FormState = {
  title: string;
  script: string;
  voiceId: string;
  speed: number;
  emotion: string;
  portraitMode: "agent" | "specific" | "sequence";
  rhythmPreset: "steady" | "balanced" | "fast";
  brollEnabled: boolean;
  maxInserts: number;
  subtitleEnabled: boolean;
  subtitleStyle: string;
  bgmEnabled: boolean;
  bgmVolume: number;
  coverMode: "none" | "frame" | "ai";
};

const defaults: FormState = {
  title: "",
  script: "先指出内容生产低效。再展示 Case Memory 如何复用经验。最后推动发布复盘。",
  voiceId: "voice_sandbox",
  speed: 1,
  emotion: "neutral",
  portraitMode: "agent",
  rhythmPreset: "balanced",
  brollEnabled: true,
  maxInserts: 4,
  subtitleEnabled: true,
  subtitleStyle: "douyin",
  bgmEnabled: false,
  bgmVolume: 0.25,
  coverMode: "frame",
};

export default function StudioCreatePage() {
  const { caseId = "" } = useParams();
  const navigate = useNavigate();
  const [form, setForm] = useState<FormState>(defaults);
  const [formError, setFormError] = useState<unknown>(null);
  const caseDetail = useQuery({
    queryKey: ["case", caseId],
    queryFn: () => api.cases.detail(caseId),
    enabled: Boolean(caseId),
  });
  const voices = useQuery({
    queryKey: ["voices"],
    queryFn: api.voices.list,
  });
  const voiceOptions = useMemo(() => voices.data?.items.filter((voice) => voice.enabled) ?? [], [voices.data?.items]);
  const selectedVoice = form.voiceId || voiceOptions[0]?.id || "voice_sandbox";
  const createJob = useMutation({
    mutationFn: () =>
      api.jobs.createDigitalHumanVideo({
        schema_version: "digital_human_video_request.v1",
        case_id: caseId,
        title: form.title.trim() || null,
        script: form.script.trim(),
        publish_content: "",
        workflow_template_id: "digital_human_v2",
        voice: {
          voice_id: selectedVoice,
          speed: form.speed,
          emotion: form.emotion.trim() || "neutral",
          volume: 1,
        },
        portrait: {
          template_mode: form.portraitMode,
          rhythm_preset: form.rhythmPreset,
          template_sequence_ids: [],
        },
        broll: {
          enabled: form.brollEnabled,
          max_inserts: form.maxInserts,
          min_segment_duration: 3,
        },
        subtitle: {
          enabled: form.subtitleEnabled,
          style_preset: form.subtitleStyle.trim() || "douyin",
        },
        bgm: {
          enabled: form.bgmEnabled,
          volume: form.bgmVolume,
          auto_mix: true,
        },
        cover: {
          mode: form.coverMode,
        },
        lipsync: {
          enabled: true,
          provider_profile_id: "runninghub.heygem.default",
          video_extension: false,
          timeout_minutes: 30,
        },
        strictness: {
          strict_timestamps: false,
          portrait_insufficient_policy: "hard_fail",
          broll_insufficient_policy: "soft_degrade",
          bgm_unavailable_policy: "soft_degrade",
          strict_cost_pricing: false,
        },
      }),
    onSuccess: (data) => {
      const runId = data.initial_run?.id;
      navigate(runId ? `${routes.caseRuns(caseId)}?run=${encodeURIComponent(runId)}` : routes.caseRuns(caseId));
    },
    onError: (error: ApiError) => setFormError(error),
  });

  if (caseDetail.isLoading) {
    return <LoadingState />;
  }

  return (
    <section className="pageStack">
      <header className="pageHeader">
        <div>
          <h1>{caseDetail.data?.name ?? "创作"}</h1>
          <p>{caseDetail.data?.product || caseDetail.data?.industry || "输入脚本并提交生产任务。"}</p>
        </div>
      </header>
      <StudioTabs caseId={caseId} />
      {caseDetail.error ? <ErrorState error={caseDetail.error} /> : null}
      <form
        className="studioGrid"
        onSubmit={(event) => {
          event.preventDefault();
          setFormError(null);
          createJob.mutate();
        }}
      >
        <section className="surface formSection">
          <div className="sectionHeader">
            <h2>脚本</h2>
            <button className="primaryButton" type="submit" disabled={createJob.isPending || !form.script.trim()}>
              {createJob.isPending ? <Loader2 size={16} className="spin" /> : <Play size={16} />}
              <span>提交 Run</span>
            </button>
          </div>
          <label>
            <span>标题</span>
            <input
              value={form.title}
              onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
              placeholder="留空时使用脚本摘要"
            />
          </label>
          <label>
            <span>脚本正文</span>
            <textarea
              value={form.script}
              onChange={(event) => setForm((current) => ({ ...current, script: event.target.value }))}
              required
            />
          </label>
          {formError ? <ErrorState error={formError} /> : null}
        </section>

        <aside className="surface formSection">
          <details open>
            <summary>声音</summary>
            <label>
              <span>Voice</span>
              <select
                value={selectedVoice}
                onChange={(event) => setForm((current) => ({ ...current, voiceId: event.target.value }))}
              >
                {voiceOptions.length === 0 ? <option value="voice_sandbox">voice_sandbox</option> : null}
                {voiceOptions.map((voice) => (
                  <option value={voice.id} key={voice.id}>
                    {voice.display_name}
                  </option>
                ))}
              </select>
            </label>
            <div className="twoCol">
              <label>
                <span>语速</span>
                <input
                  type="number"
                  min={0.5}
                  max={2}
                  step={0.1}
                  value={form.speed}
                  onChange={(event) => setForm((current) => ({ ...current, speed: Number(event.target.value) }))}
                />
              </label>
              <label>
                <span>情绪</span>
                <input
                  value={form.emotion}
                  onChange={(event) => setForm((current) => ({ ...current, emotion: event.target.value }))}
                />
              </label>
            </div>
          </details>
          <details open>
            <summary>数字人</summary>
            <div className="twoCol">
              <label>
                <span>模板模式</span>
                <select
                  value={form.portraitMode}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, portraitMode: event.target.value as FormState["portraitMode"] }))
                  }
                >
                  <option value="agent">自动</option>
                  <option value="specific">指定模板</option>
                  <option value="sequence">模板序列</option>
                </select>
              </label>
              <label>
                <span>节奏</span>
                <select
                  value={form.rhythmPreset}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, rhythmPreset: event.target.value as FormState["rhythmPreset"] }))
                  }
                >
                  <option value="steady">稳</option>
                  <option value="balanced">均衡</option>
                  <option value="fast">快</option>
                </select>
              </label>
            </div>
          </details>
          <details open>
            <summary>包装</summary>
            <label className="toggleLine">
              <input
                type="checkbox"
                checked={form.brollEnabled}
                onChange={(event) => setForm((current) => ({ ...current, brollEnabled: event.target.checked }))}
              />
              <span>B-roll</span>
            </label>
            <label>
              <span>B-roll 最大插入数</span>
              <input
                type="number"
                min={0}
                max={20}
                value={form.maxInserts}
                onChange={(event) => setForm((current) => ({ ...current, maxInserts: Number(event.target.value) }))}
              />
            </label>
            <label className="toggleLine">
              <input
                type="checkbox"
                checked={form.subtitleEnabled}
                onChange={(event) => setForm((current) => ({ ...current, subtitleEnabled: event.target.checked }))}
              />
              <span>字幕</span>
            </label>
            <label>
              <span>字幕样式</span>
              <input
                value={form.subtitleStyle}
                onChange={(event) => setForm((current) => ({ ...current, subtitleStyle: event.target.value }))}
              />
            </label>
            <label className="toggleLine">
              <input
                type="checkbox"
                checked={form.bgmEnabled}
                onChange={(event) => setForm((current) => ({ ...current, bgmEnabled: event.target.checked }))}
              />
              <span>BGM</span>
            </label>
            <label>
              <span>BGM 音量</span>
              <input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={form.bgmVolume}
                onChange={(event) => setForm((current) => ({ ...current, bgmVolume: Number(event.target.value) }))}
              />
            </label>
            <label>
              <span>封面</span>
              <select
                value={form.coverMode}
                onChange={(event) =>
                  setForm((current) => ({ ...current, coverMode: event.target.value as FormState["coverMode"] }))
                }
              >
                <option value="frame">取帧</option>
                <option value="ai">AI</option>
                <option value="none">无</option>
              </select>
            </label>
          </details>
        </aside>
      </form>
    </section>
  );
}
