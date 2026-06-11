import { PLATFORM_OPTIONS, platformLabel } from "./publishModel";

type PlatformChipsProps = {
  value: string[];
  onChange?: (platforms: string[]) => void;
  compact?: boolean;
};

export function PlatformChips({ value, onChange, compact = false }: PlatformChipsProps) {
  const selected = new Set(value);

  if (!onChange) {
    return (
      <div className="flex flex-wrap gap-1.5">
        {value.map((platform) => (
          <span key={platform} className="badge-info">
            {platformLabel(platform)}
          </span>
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      {PLATFORM_OPTIONS.map((option) => {
        const active = selected.has(option.value);
        return (
          <button
            key={option.value}
            type="button"
            className={`rounded-full border px-3 py-1.5 text-sm font-medium transition ${
              active
                ? "border-accent/25 bg-accent/15 text-accent"
                : "border-border/75 bg-white/65 text-text-secondary hover:bg-white/85"
            } ${compact ? "px-2.5 py-1 text-xs" : ""}`}
            onClick={() => {
              const next = active ? value.filter((item) => item !== option.value) : [...value, option.value];
              onChange(next.length > 0 ? next : [option.value]);
            }}
          >
            {option.label}
            {"pending" in option && option.pending ? <span className="ml-1 text-[10px] text-status-warning">待接入</span> : null}
          </button>
        );
      })}
    </div>
  );
}
