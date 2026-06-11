import { getStatusPresentation, toneClassNames } from "../../lib/status";

export function StatusPill({ status, label }: { status?: string | null; label?: string }) {
  const presentation = getStatusPresentation(status);
  const Icon = presentation.icon;
  return (
    <span className={`statusPill ${toneClassNames[presentation.tone]}`} title={status ?? undefined}>
      <Icon className={`h-3.5 w-3.5 ${presentation.spinning ? "animate-spin" : ""}`} />
      <span>{label ?? presentation.label}</span>
    </span>
  );
}
