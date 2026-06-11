import { useEffect, useMemo, useState } from "react";
import type { ScriptToolItem } from "./scriptToolModel";
import { trimScriptToolList } from "./scriptToolModel";

const CANDIDATE_KEY = "m6ar_r6_script_candidates_v1";
const HISTORY_KEY = "m6ar_r6_script_history_v1";

function readItems(key: string): ScriptToolItem[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeItems(key: string, items: ScriptToolItem[]) {
  if (typeof window !== "undefined") localStorage.setItem(key, JSON.stringify(items));
}

export function useScriptToolbox(caseId: string) {
  const [candidates, setCandidates] = useState<ScriptToolItem[]>(() => readItems(CANDIDATE_KEY));
  const [history, setHistory] = useState<ScriptToolItem[]>(() => readItems(HISTORY_KEY));

  useEffect(() => writeItems(CANDIDATE_KEY, candidates), [candidates]);
  useEffect(() => writeItems(HISTORY_KEY, history), [history]);

  const caseCandidates = useMemo(() => candidates.filter((item) => item.caseId === caseId), [candidates, caseId]);
  const caseHistory = useMemo(() => trimScriptToolList(history.filter((item) => item.caseId === caseId), 30), [history, caseId]);

  return {
    candidates: caseCandidates,
    history: caseHistory,
    addCandidate: (item: ScriptToolItem) =>
      setCandidates((current) => trimScriptToolList([item, ...current.filter((entry) => entry.id !== item.id)], 100)),
    removeCandidate: (id: string) => setCandidates((current) => current.filter((item) => item.id !== id)),
    clearCandidates: () => setCandidates((current) => current.filter((item) => item.caseId !== caseId)),
    appendHistory: (items: ScriptToolItem[]) =>
      setHistory((current) => trimScriptToolList([...items, ...current], 120)),
  };
}
