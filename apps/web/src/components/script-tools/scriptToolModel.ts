export type ScriptToolItem = {
  id: string;
  caseId: string;
  title: string;
  script: string;
  source: "sandbox" | "candidate" | "history";
  createdAt: string;
};

export type ScriptToolMode = "generate" | "polish";

export function newScriptToolId(prefix: string) {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return `${prefix}_${crypto.randomUUID()}`;
  return `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

export function trimScriptToolList(items: ScriptToolItem[], limit = 30) {
  return [...items]
    .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
    .slice(0, limit);
}

export function buildGenerationBrief({
  mode,
  goal,
  topic,
  currentScript,
  index,
}: {
  mode: ScriptToolMode;
  goal: string;
  topic: string;
  currentScript: string;
  index: number;
}) {
  const lines = [
    mode === "polish" ? "请润色当前脚本，保留事实与核心卖点。" : "请生成一版新的短视频脚本。",
    goal.trim() ? `目标：${goal.trim()}` : "",
    topic.trim() ? `主题提示：${topic.trim()}` : "",
    currentScript.trim() ? `当前脚本：${currentScript.trim()}` : "",
    `版本序号：${index + 1}`,
  ].filter(Boolean);
  return `${lines.join("\n")}\n\n请输出可直接用于数字人视频的中文口播脚本。`;
}
