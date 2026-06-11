import { formatAbsoluteTime, formatRelativeTime } from "../lib/format";

export function TimeText({ value }: { value?: string | null }) {
  return (
    <time dateTime={value ?? undefined} title={formatAbsoluteTime(value)}>
      {formatRelativeTime(value)}
    </time>
  );
}
