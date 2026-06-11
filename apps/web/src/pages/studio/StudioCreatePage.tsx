import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Captions,
  ChevronLeft,
  ChevronRight,
  Film,
  Loader2,
  Mic2,
  Music,
  Play,
  Settings2,
  Sparkles,
  Volume2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type ApiError } from "../../api/client";
import { ErrorState, LoadingState } from "../../components/State";
import { StudioTabs } from "../../components/StudioTabs";
import { useToast } from "../../components/Toast";
import { FlowStepper } from "../../components/ui/FlowStepper";
import { routes } from "../../routes";
import { shortId } from "../../lib/format";

type StudioStep = 0 | 1 | 2 | 3 | 4;

type LipSyncPreset = "balanced" | "large_motion" | "strict_face" | "audio_priority";

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
  subtitleStyle: "douyin" | "clean" | "variety" | "news" | "movie" | "youshe_title_black";
  subtitleSize: number;
  bgmEnabled: boolean;
  bgmVolume: number;
  bgmAutoMix: boolean;
  coverMode: "none" | "frame" | "ai";
  lipsyncEnabled: boolean;
  lipsyncPreset: LipSyncPreset;
  lipsyncVideoExtension: boolean;
  lipsyncTimeoutMinutes: number;
};

const STORAGE_KEY = "m6ar_studio_create_preferences_v1";

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
  subtitleSize: 28,
  bgmEnabled: false,
  bgmVolume: 0.25,
  bgmAutoMix: true,
  coverMode: "frame",
  lipsyncEnabled: true,
  lipsyncPreset: "balanced",
  lipsyncVideoExtension: false,
  lipsyncTimeoutMinutes: 30,
};

const steps = ["脚本", "模板", "成片配置", "后处理", "提交"] as const;

const emotionOptions = [
  { value: "neutral", label: "自然" },
  { value: "happy", label: "明快" },
  { value: "serious", label: "沉稳" },
  { value: "energetic", label: "有力" },
] as const;

const lipsyncPresets: Record<LipSyncPreset, { label: string; description: string; videoExtension: boolean }> = {
  balanced: { label: "标准均衡", description: "通用场景默认策略，兼顾锁脸稳定性与匹配成功率。", videoExtension: false },
  large_motion: { label: "大幅头动", description: "适合转头、抬头、位移较大场景，提高匹配宽容度。", videoExtension: false },
  strict_face: { label: "严格锁脸", description: "适合固定机位单人视频，减少误匹配。", videoExtension: false },
  audio_priority: { label: "时长优先", description: "音频较长时自动延长视频，避免尾部被截断。", videoExtension: true },
};

function clampNumber(value: number, min: number, max: number, fallback: number) {
  if (Number.isNaN(value)) return fallback;
  return Math.max(min, Math.min(max, value));
}

function loadStoredForm(): FormState {
  if (typeof window === "undefined") return defaults;
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (!saved) return defaults;
    const parsed = JSON.parse(saved) as Partial<FormState>;
    return {
      ...defaults,
      ...parsed,
      speed: clampNumber(Number(parsed.speed ?? defaults.speed), 0.5, 2, defaults.speed),
      maxInserts: clampNumber(Number(parsed.maxInserts ?? defaults.maxInserts), 0, 20, defaults.maxInserts),
      subtitleSize: clampNumber(Number(parsed.subtitleSize ?? defaults.subtitleSize), 12, 96, defaults.subtitleSize),
      bgmVolume: clampNumber(Number(parsed.bgmVolume ?? defaults.bgmVolume), 0, 1, defaults.bgmVolume),
      lipsyncTimeoutMinutes: clampNumber(
        Number(parsed.lipsyncTimeoutMinutes ?? defaults.lipsyncTimeoutMinutes),
        5,
        90,
        defaults.lipsyncTimeoutMinutes,
      ),
    };
  } catch {
    return defaults;
  }
}

function validateStep(step: StudioStep, form: FormState, selectedVoice: string) {
  if (step === 0 && !form.script.trim()) return "请先输入脚本正文";
  if (step === 1 && form.portraitMode !== "agent") return "当前版本请使用自动模板，指定模板和序列将在素材库里程碑接入";
  if (step === 2 && !selectedVoice) return "请选择可用声音";
  if (step === 2 && (form.speed < 0.5 || form.speed > 2)) return "语速需在 0.5 到 2.0 之间";
  if (step === 3 && form.subtitleEnabled && (form.subtitleSize < 12 || form.subtitleSize > 96)) return "字幕字号需在 12 到 96 之间";
  if (step === 3 && form.bgmEnabled && (form.bgmVolume < 0 || form.bgmVolume > 1)) return "BGM 音量需在 0 到 100% 之间";
  return null;
}

function validateAll(form: FormState, selectedVoice: string) {
  for (let index = 0; index < steps.length - 1; index += 1) {
    const message = validateStep(index as StudioStep, form, selectedVoice);
    if (message) return { step: index as StudioStep, message };
  }
  return null;
}

export default function StudioCreatePage() {
  const { caseId = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [step, setStep] = useState<StudioStep>(0);
  const [form, setForm] = useState<FormState>(loadStoredForm);
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
  const selectedVoiceLabel = voiceOptions.find((voice) => voice.id === selectedVoice)?.display_name ?? selectedVoice;
  const scriptCount = form.script.trim().length;

  useEffect(() => {
    const { title, script, ...preferences } = form;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
  }, [form]);

  useEffect(() => {
    if (!voices.data || voiceOptions.length === 0) return;
    if (!voiceOptions.some((voice) => voice.id === form.voiceId)) {
      setForm((current) => ({ ...current, voiceId: voiceOptions[0].id }));
      toast.warning("已恢复默认声音", "上次选择的声音不可用或已删除");
    }
  }, [form.voiceId, toast, voiceOptions, voices.data]);

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
          font_size: form.subtitleSize,
        },
        bgm: {
          enabled: form.bgmEnabled,
          volume: form.bgmVolume,
          auto_mix: form.bgmAutoMix,
        },
        cover: {
          mode: form.coverMode,
        },
        lipsync: {
          enabled: form.lipsyncEnabled,
          provider_profile_id: "runninghub.heygem.default",
          video_extension: form.lipsyncVideoExtension,
          timeout_minutes: form.lipsyncTimeoutMinutes,
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
      toast.success("任务提交成功", runId ? `Run ${shortId(runId)}` : undefined);
      window.setTimeout(() => {
        navigate(runId ? `${routes.caseOutputs(caseId)}?run=${encodeURIComponent(runId)}` : routes.caseOutputs(caseId));
      }, 1500);
    },
    onError: (error: ApiError) => setFormError(error),
  });

  function setField<Key extends keyof FormState>(key: Key, value: FormState[Key]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function goToStep(next: StudioStep) {
    if (next <= step) {
      setStep(next);
      return;
    }
    const message = validateStep(step, form, selectedVoice);
    if (message) {
      toast.warning("当前步骤未完成", message);
      return;
    }
    setStep(next);
  }

  function submit() {
    const invalid = validateAll(form, selectedVoice);
    if (invalid) {
      setStep(invalid.step);
      toast.warning("无法提交", invalid.message);
      return;
    }
    setFormError(null);
    createJob.mutate();
  }

  if (caseDetail.isLoading) {
    return <LoadingState />;
  }

  return (
    <section className="pageStack">
      <header className="pageHeader">
        <div>
          <h1>{caseDetail.data?.name ?? "创作"}</h1>
          <p>{caseDetail.data?.product || caseDetail.data?.industry || "按步骤完成脚本、模板、成片配置与后处理。"}</p>
        </div>
      </header>
      <StudioTabs caseId={caseId} />
      {caseDetail.error ? <ErrorState error={caseDetail.error} /> : null}

      <div className="card">
        <FlowStepper
          steps={steps}
          activeStep={step}
          onStepClick={(next) => goToStep(next as StudioStep)}
          ariaLabel="创作流程步骤"
        />
      </div>

      <form
        className="grid gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(320px,0.75fr)]"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <section className="card grid gap-5">
          {step === 0 ? (
            <ScriptStep form={form} setField={setField} scriptCount={scriptCount} />
          ) : step === 1 ? (
            <TemplateStep form={form} setField={setField} />
          ) : step === 2 ? (
            <ProductionStep
              form={form}
              setField={setField}
              selectedVoice={selectedVoice}
              voiceOptions={voiceOptions}
            />
          ) : step === 3 ? (
            <PostProcessStep form={form} setField={setField} />
          ) : (
            <SubmitStep form={form} selectedVoiceLabel={selectedVoiceLabel} scriptCount={scriptCount} />
          )}

          {formError ? <ErrorState error={formError} /> : null}

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/70 pt-4">
            <button
              className="btn-secondary"
              type="button"
              disabled={step === 0 || createJob.isPending}
              onClick={() => setStep((current) => Math.max(0, current - 1) as StudioStep)}
            >
              <ChevronLeft className="h-4 w-4" />
              <span>上一步</span>
            </button>
            {step < 4 ? (
              <button
                className="btn-primary"
                type="button"
                onClick={() => goToStep((step + 1) as StudioStep)}
                disabled={Boolean(validateStep(step, form, selectedVoice))}
              >
                <span>下一步</span>
                <ChevronRight className="h-4 w-4" />
              </button>
            ) : (
              <button className="btn-primary" type="submit" disabled={createJob.isPending}>
                {createJob.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                <span>提交成片任务</span>
              </button>
            )}
          </div>
        </section>

        <aside className="card grid content-start gap-4">
          <div>
            <h2 className="text-lg font-semibold text-text-primary">配置摘要</h2>
            <p className="text-sm">偏好会自动保存，刷新页面后继续沿用。</p>
          </div>
          <SummaryRow icon={Mic2} label="声音" value={`${selectedVoiceLabel} · ${form.speed.toFixed(1)}x`} />
          <SummaryRow icon={Film} label="模板" value={`${portraitModeLabel(form.portraitMode)} · ${rhythmLabel(form.rhythmPreset)}`} />
          <SummaryRow
            icon={Sparkles}
            label="口型"
            value={form.lipsyncEnabled ? lipsyncPresets[form.lipsyncPreset].label : "关闭"}
          />
          <SummaryRow
            icon={Captions}
            label="字幕"
            value={form.subtitleEnabled ? `${subtitleLabel(form.subtitleStyle)} · ${form.subtitleSize}px` : "关闭"}
          />
          <SummaryRow icon={Music} label="BGM" value={form.bgmEnabled ? `${Math.round(form.bgmVolume * 100)}%` : "关闭"} />
          <div className="rounded-2xl border border-border/70 bg-white/60 p-3">
            <p className="text-xs text-text-tertiary">脚本字符数</p>
            <p className={`mt-1 font-mono text-2xl font-bold ${scriptCount === 0 ? "text-status-error" : "text-text-primary"}`}>
              {scriptCount}
            </p>
          </div>
        </aside>
      </form>
    </section>
  );
}

function ScriptStep({
  form,
  setField,
  scriptCount,
}: {
  form: FormState;
  setField: <Key extends keyof FormState>(key: Key, value: FormState[Key]) => void;
  scriptCount: number;
}) {
  return (
    <div className="grid gap-4">
      <SectionTitle icon={Sparkles} title="脚本" description="先确定标题和正文，脚本为空时不能进入下一步。" />
      <label>
        <span>标题</span>
        <input value={form.title} onChange={(event) => setField("title", event.target.value)} placeholder="留空时使用脚本摘要" />
      </label>
      <label>
        <span className={scriptCount === 0 ? "text-status-error" : undefined}>脚本正文</span>
        <textarea
          value={form.script}
          onChange={(event) => setField("script", event.target.value)}
          required
          className={scriptCount === 0 ? "border-status-error/40 bg-status-error/5" : undefined}
        />
      </label>
      <div className="flex items-center justify-between text-xs text-text-secondary">
        <span>{scriptCount === 0 ? "请输入脚本后继续" : "脚本已就绪"}</span>
        <span className="font-mono tabular-nums">{scriptCount} 字</span>
      </div>
    </div>
  );
}

function TemplateStep({
  form,
  setField,
}: {
  form: FormState;
  setField: <Key extends keyof FormState>(key: Key, value: FormState[Key]) => void;
}) {
  const options: Array<{ value: FormState["portraitMode"]; label: string; detail: string }> = [
    { value: "agent", label: "自动模板", detail: "由系统按脚本和案例素材选择人像模板。" },
    { value: "specific", label: "指定模板", detail: "素材库接入后可选择固定模板。" },
    { value: "sequence", label: "模板序列", detail: "素材库接入后可编排模板序列。" },
  ];
  return (
    <div className="grid gap-4">
      <SectionTitle icon={Film} title="模板" description="本阶段沿用 M6a-1 的自动模板策略，指定模板与序列后续接入素材库。" />
      <div className="grid gap-3 md:grid-cols-3">
        {options.map((option) => (
          <button
            type="button"
            key={option.value}
            onClick={() => setField("portraitMode", option.value)}
            className={`rounded-[20px] border p-4 text-left transition-all ${
              form.portraitMode === option.value ? "border-accent/35 bg-accent/10" : "border-border/70 bg-white/60"
            }`}
          >
            <span className="font-semibold text-text-primary">{option.label}</span>
            <span className="mt-2 block text-sm text-text-secondary">{option.detail}</span>
          </button>
        ))}
      </div>
      {form.portraitMode !== "agent" ? (
        <div className="stateBox danger">
          <span>当前版本请切回自动模板后继续。</span>
        </div>
      ) : null}
      <label>
        <span>剪辑节奏</span>
        <select value={form.rhythmPreset} onChange={(event) => setField("rhythmPreset", event.target.value as FormState["rhythmPreset"])}>
          <option value="steady">稳</option>
          <option value="balanced">均衡</option>
          <option value="fast">快</option>
        </select>
      </label>
    </div>
  );
}

function ProductionStep({
  form,
  setField,
  selectedVoice,
  voiceOptions,
}: {
  form: FormState;
  setField: <Key extends keyof FormState>(key: Key, value: FormState[Key]) => void;
  selectedVoice: string;
  voiceOptions: Array<{ id: string; display_name: string }>;
}) {
  return (
    <div className="grid gap-4">
      <SectionTitle icon={Mic2} title="成片配置" description="配置声音、口型同步和 B-roll 策略。" />
      <label>
        <span className={!selectedVoice ? "text-status-error" : undefined}>声音</span>
        <select value={selectedVoice} onChange={(event) => setField("voiceId", event.target.value)}>
          {voiceOptions.length === 0 ? <option value="voice_sandbox">沙盒声音</option> : null}
          {voiceOptions.map((voice) => (
            <option value={voice.id} key={voice.id}>
              {voice.display_name}
            </option>
          ))}
        </select>
      </label>
      <div className="grid gap-3 md:grid-cols-2">
        <label>
          <span>语速</span>
          <input type="number" min={0.5} max={2} step={0.1} value={form.speed} onChange={(event) => setField("speed", Number(event.target.value))} />
        </label>
        <label>
          <span>情绪</span>
          <select value={form.emotion} onChange={(event) => setField("emotion", event.target.value)}>
            {emotionOptions.map((option) => (
              <option value={option.value} key={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <ToggleLine checked={form.lipsyncEnabled} onChange={(checked) => setField("lipsyncEnabled", checked)} label="启用口型同步" />
      {form.lipsyncEnabled ? (
        <div className="grid gap-3 rounded-[20px] border border-border/70 bg-white/60 p-4">
          <div className="grid gap-3 md:grid-cols-2">
            {(Object.keys(lipsyncPresets) as LipSyncPreset[]).map((preset) => (
              <button
                type="button"
                key={preset}
                onClick={() => {
                  setField("lipsyncPreset", preset);
                  setField("lipsyncVideoExtension", lipsyncPresets[preset].videoExtension);
                }}
                className={`rounded-2xl border p-3 text-left ${
                  form.lipsyncPreset === preset ? "border-accent/35 bg-accent/10" : "border-border/70 bg-white/70"
                }`}
              >
                <span className="font-medium text-text-primary">{lipsyncPresets[preset].label}</span>
                <span className="mt-1 block text-xs text-text-secondary">{lipsyncPresets[preset].description}</span>
              </button>
            ))}
          </div>
          <ToggleLine checked={form.lipsyncVideoExtension} onChange={(checked) => setField("lipsyncVideoExtension", checked)} label="允许视频时长扩展" />
          <label>
            <span>超时时间（分钟）</span>
            <input
              type="number"
              min={5}
              max={90}
              value={form.lipsyncTimeoutMinutes}
              onChange={(event) => setField("lipsyncTimeoutMinutes", Number(event.target.value))}
            />
          </label>
        </div>
      ) : null}
      <ToggleLine checked={form.brollEnabled} onChange={(checked) => setField("brollEnabled", checked)} label="启用 B-roll 插入" />
      {form.brollEnabled ? (
        <label>
          <span>B-roll 最大插入数</span>
          <input type="number" min={0} max={20} value={form.maxInserts} onChange={(event) => setField("maxInserts", Number(event.target.value))} />
        </label>
      ) : null}
    </div>
  );
}

function PostProcessStep({
  form,
  setField,
}: {
  form: FormState;
  setField: <Key extends keyof FormState>(key: Key, value: FormState[Key]) => void;
}) {
  return (
    <div className="grid gap-4">
      <SectionTitle icon={Settings2} title="后处理" description="配置字幕、BGM 和封面策略。" />
      <ToggleLine checked={form.subtitleEnabled} onChange={(checked) => setField("subtitleEnabled", checked)} label="启用字幕" />
      {form.subtitleEnabled ? (
        <div className="grid gap-3 md:grid-cols-2">
          <label>
            <span>字幕样式</span>
            <select value={form.subtitleStyle} onChange={(event) => setField("subtitleStyle", event.target.value as FormState["subtitleStyle"])}>
              <option value="douyin">抖音风</option>
              <option value="clean">简洁风</option>
              <option value="variety">综艺风</option>
              <option value="news">新闻风</option>
              <option value="movie">电影风</option>
              <option value="youshe_title_black">标题黑风</option>
            </select>
          </label>
          <label>
            <span>字幕字号</span>
            <input type="number" min={12} max={96} value={form.subtitleSize} onChange={(event) => setField("subtitleSize", Number(event.target.value))} />
          </label>
        </div>
      ) : null}
      <ToggleLine checked={form.bgmEnabled} onChange={(checked) => setField("bgmEnabled", checked)} label="启用 BGM" />
      {form.bgmEnabled ? (
        <div className="grid gap-3 rounded-[20px] border border-border/70 bg-white/60 p-4">
          <VolumeSlider value={form.bgmVolume} onChange={(value) => setField("bgmVolume", value)} />
          <ToggleLine checked={form.bgmAutoMix} onChange={(checked) => setField("bgmAutoMix", checked)} label="自动混音" />
        </div>
      ) : null}
      <label>
        <span>封面</span>
        <select value={form.coverMode} onChange={(event) => setField("coverMode", event.target.value as FormState["coverMode"])}>
          <option value="frame">取帧</option>
          <option value="ai">AI 生成</option>
          <option value="none">不生成</option>
        </select>
      </label>
    </div>
  );
}

function SubmitStep({ form, selectedVoiceLabel, scriptCount }: { form: FormState; selectedVoiceLabel: string; scriptCount: number }) {
  return (
    <div className="grid gap-4">
      <SectionTitle icon={Play} title="提交" description="确认配置后提交生产任务，成功后自动跳转到成片页。" />
      <div className="grid gap-3 md:grid-cols-2">
        <ReviewItem label="脚本" value={`${scriptCount} 字`} />
        <ReviewItem label="声音" value={`${selectedVoiceLabel} · ${form.speed.toFixed(1)}x`} />
        <ReviewItem label="模板" value={`${portraitModeLabel(form.portraitMode)} · ${rhythmLabel(form.rhythmPreset)}`} />
        <ReviewItem label="口型" value={form.lipsyncEnabled ? lipsyncPresets[form.lipsyncPreset].label : "关闭"} />
        <ReviewItem label="字幕" value={form.subtitleEnabled ? `${subtitleLabel(form.subtitleStyle)} · ${form.subtitleSize}px` : "关闭"} />
        <ReviewItem label="BGM" value={form.bgmEnabled ? `${Math.round(form.bgmVolume * 100)}%` : "关闭"} />
      </div>
    </div>
  );
}

function SectionTitle({ icon: Icon, title, description }: { icon: typeof Sparkles; title: string; description: string }) {
  return (
    <div className="flex items-start gap-3">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-accent/10 text-accent">
        <Icon className="h-5 w-5" />
      </span>
      <div>
        <h2 className="text-lg font-semibold text-text-primary">{title}</h2>
        <p className="text-sm">{description}</p>
      </div>
    </div>
  );
}

function ToggleLine({ checked, onChange, label }: { checked: boolean; onChange: (checked: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex items-center justify-between gap-3 rounded-2xl border border-border/70 bg-white/60 px-4 py-3 text-left"
    >
      <span className="font-medium text-text-primary">{label}</span>
      <span className={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full transition-colors ${checked ? "bg-accent" : "bg-surface-hover"}`}>
        <span className={`inline-block h-5 w-5 rounded-full bg-white transition-transform ${checked ? "translate-x-6" : "translate-x-1"}`} />
      </span>
    </button>
  );
}

function VolumeSlider({ value, onChange }: { value: number; onChange: (value: number) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-3 sm:flex-nowrap">
      <span className="w-16 shrink-0 text-sm text-text-secondary">音量</span>
      <Volume2 className="h-4 w-4 text-text-tertiary" />
      <input
        type="range"
        min={0}
        max={1}
        step={0.05}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="min-w-[150px] flex-1 accent-accent"
      />
      <span className="w-12 shrink-0 text-right font-mono text-sm text-text-primary">{Math.round(value * 100)}%</span>
    </div>
  );
}

function SummaryRow({ icon: Icon, label, value }: { icon: typeof Sparkles; label: string; value: string }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-border/70 bg-white/60 p-3">
      <Icon className="h-4 w-4 text-accent" />
      <div className="min-w-0">
        <p className="text-xs text-text-tertiary">{label}</p>
        <p className="truncate text-sm font-medium text-text-primary">{value}</p>
      </div>
    </div>
  );
}

function ReviewItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-border/70 bg-white/60 p-3">
      <p className="text-xs text-text-tertiary">{label}</p>
      <p className="mt-1 font-medium text-text-primary">{value}</p>
    </div>
  );
}

function portraitModeLabel(value: FormState["portraitMode"]) {
  if (value === "agent") return "自动模板";
  if (value === "specific") return "指定模板";
  return "模板序列";
}

function rhythmLabel(value: FormState["rhythmPreset"]) {
  if (value === "steady") return "稳";
  if (value === "fast") return "快";
  return "均衡";
}

function subtitleLabel(value: FormState["subtitleStyle"]) {
  if (value === "clean") return "简洁风";
  if (value === "variety") return "综艺风";
  if (value === "news") return "新闻风";
  if (value === "movie") return "电影风";
  if (value === "youshe_title_black") return "标题黑风";
  return "抖音风";
}
