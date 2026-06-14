export type ScriptToolItem = {
  id: string;
  caseId: string;
  title: string;
  script: string;
  source: "ai" | "candidate" | "history";
  createdAt: string;
};

export type ScriptToolMode = "generate" | "polish";

// 场景（业务语言）= 后端 persona_mode：硬广投流 / IP 人设号。
export type SceneType = "hard_ad" | "ip_persona";
// 创作模式（业务语言）= 后端 operation 的子集：全新创作 / 参考爆款 / 爆款复刻。
export type CreationMode = "fresh" | "remix" | "clone";
// 后端 operation 取值（含润色等内部操作）。
export type ScriptOperation = "polish" | "fresh" | "remix" | "clone" | "generate" | "semantic";

export const SCENE_META: Record<SceneType, { label: string; description: string }> = {
  hard_ad: { label: "硬广投流", description: "追求极致 ROI 和线索转化" },
  ip_persona: { label: "IP 人设号", description: "追求粉丝粘性与信任感" },
};

export const SCENE_OPTIONS: SceneType[] = ["hard_ad", "ip_persona"];

export const CREATION_MODE_META: Record<
  CreationMode,
  { title: string; description: string; requiresReference: boolean; inputHint: string; placeholder: string }
> = {
  fresh: {
    title: "全新创作",
    description: "优先新切口、新结构，自动避开最近重复表达",
    requiresReference: false,
    inputHint: "（可选，输入一句 idea、场景、限制或想讲的点）",
    placeholder: "比如：别总讲价格，换成「修坏一次比贵几十块更亏」；或者直接留空让系统自由创作…",
  },
  remix: {
    title: "参考爆款",
    description: "参考爆款骨架和节奏，重写成当前 case，主动拉开与原文距离",
    requiresReference: true,
    inputHint: "（必填，系统会参考爆款骨架和节奏重写成当前 case）",
    placeholder: "粘贴同行爆款文案，系统会参考它的节奏、结构和叙述逻辑，重写成当前 case，不会直接照抄原句…",
  },
  clone: {
    title: "爆款复刻",
    description: "语言风格、脚本结构都参考爆款，仅替换品牌与部分表达",
    requiresReference: true,
    inputHint: "（必填，系统会尽量保留话风和结构，只替换品牌与关键信息）",
    placeholder: "粘贴同行爆款文案，系统会尽量沿用它的语言风格、脚本结构和节奏，只做品牌替换与简单洗稿…",
  },
};

export const CREATION_MODE_OPTIONS: CreationMode[] = ["fresh", "remix", "clone"];

// 策略标签（可多选），按场景区分；name 即发送给后端的标签文本。
export const STRATEGY_TAGS: Record<SceneType, { id: string; name: string; description: string }[]> = {
  hard_ad: [
    { id: "hard-ad-hook", name: "开场钩子", description: "视频前 3 秒的吸引注意内容" },
    { id: "hard-ad-pain", name: "痛点挖掘", description: "戳中用户痛点的内容" },
    { id: "hard-ad-product", name: "产品介绍", description: "产品功能展示" },
    { id: "hard-ad-compare", name: "对比论证", description: "与竞品对比" },
    { id: "hard-ad-scenario", name: "使用场景", description: "产品使用场景" },
    { id: "hard-ad-offer", name: "限时优惠", description: "促销活动" },
    { id: "hard-ad-cta", name: "行动召唤", description: "引导用户行动" },
    { id: "hard-ad-trust", name: "信任背书", description: "权威认证 / 口碑" },
    { id: "hard-ad-emotion", name: "情感共鸣", description: "引发情感共鸣" },
    { id: "hard-ad-value", name: "干货输出", description: "提供有价值信息" },
  ],
  ip_persona: [
    { id: "ip-cold-start", name: "新号冷启动", description: "先把账号标签和基础认知打出来" },
    { id: "ip-exposure", name: "起号期增曝光", description: "优先拉完播、互动和推荐量" },
    { id: "ip-leads", name: "留资获客", description: "自然引导私信、咨询和线索沉淀" },
    { id: "ip-opinion", name: "输出观点", description: "用鲜明立场带动讨论和传播" },
    { id: "ip-persona", name: "人设立住", description: "强化身份、经历和价值观" },
    { id: "ip-avoid-pitfalls", name: "行业避坑", description: "用经验建议建立专业信任" },
    { id: "ip-story", name: "真实故事", description: "用经历或案例自然带出卖点" },
    { id: "ip-slice", name: "日常切片", description: "从工作和生活片段建立真实感" },
    { id: "ip-engage", name: "评论互动", description: "设计可讨论话题，带动互动率" },
    { id: "ip-trust", name: "信任沉淀", description: "持续积累靠谱感和复访心智" },
  ],
};

// 预估时长（仅 IP 人设号场景展示）。
export const DURATION_OPTIONS: { value: string; label: string }[] = [
  { value: "15-30s", label: "短平快（约 15-30 秒）" },
  { value: "30-60s", label: "常规（约 30-60 秒）" },
  { value: "1-2min", label: "深度长文（约 1-2 分钟）" },
];

export const GENERATION_COUNTS = [1, 2, 3, 5] as const;

export const DEFAULT_SCENE: SceneType = "hard_ad";
export const DEFAULT_CREATION_MODE: CreationMode = "fresh";

/** 创作模式 → 后端 operation；润色场景固定为 polish。 */
export function operationFor(mode: ScriptToolMode, creationMode: CreationMode): ScriptOperation {
  return mode === "polish" ? "polish" : creationMode;
}

export function newScriptToolId(prefix: string) {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return `${prefix}_${crypto.randomUUID()}`;
  return `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

export function trimScriptToolList(items: ScriptToolItem[], limit = 30) {
  return [...items]
    .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
    .slice(0, limit);
}

/**
 * 把卡片式 UI 选项组装成一段结构化中文 brief，连同 persona_mode/operation 一起发给后端。
 * 策略标签、参考文案、预估时长等都折叠进 brief 文本，模型据此改写口播脚本。
 */
export function buildGenerationBrief({
  mode,
  scene,
  creationMode,
  strategyTags,
  referenceScript,
  goal,
  duration,
  currentScript,
  index,
}: {
  mode: ScriptToolMode;
  scene: SceneType;
  creationMode: CreationMode;
  strategyTags: string[];
  referenceScript: string;
  goal: string;
  duration: string;
  currentScript: string;
  index: number;
}) {
  const sceneLabel = SCENE_META[scene].label;
  const modeTitle = mode === "polish" ? "润色现有脚本" : CREATION_MODE_META[creationMode].title;
  const lines = [
    mode === "polish"
      ? "请润色当前脚本，保留事实与核心卖点，让表达更顺、更有转化力。"
      : "请生成一版可直接拍摄的数字人口播脚本。",
    `场景：${sceneLabel}（${SCENE_META[scene].description}）`,
    `创作模式：${modeTitle}`,
    strategyTags.length ? `策略标签：${strategyTags.join("、")}` : "",
    scene === "ip_persona" && duration ? `预估时长：${duration}` : "",
    goal.trim() ? `创作目标：${goal.trim()}` : "",
    referenceScript.trim()
      ? `${mode === "polish" || creationMode === "fresh" ? "创作补充" : "参考文案"}：${referenceScript.trim()}`
      : "",
    mode === "polish" && currentScript.trim() ? `当前脚本：${currentScript.trim()}` : "",
    `版本序号：${index + 1}`,
  ].filter(Boolean);
  return `${lines.join("\n")}\n\n请输出可直接用于数字人视频的中文口播脚本。`;
}
