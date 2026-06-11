const ZH_DATE_TIME = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const ZH_RELATIVE = new Intl.RelativeTimeFormat("zh-CN", { numeric: "auto" });

export function formatAbsoluteTime(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return ZH_DATE_TIME.format(date).replaceAll("/", "-");
}

export function formatRelativeTime(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  const timestamp = date.getTime();
  if (Number.isNaN(timestamp)) return "-";
  const diffSeconds = Math.round((timestamp - Date.now()) / 1000);
  const absSeconds = Math.abs(diffSeconds);
  if (absSeconds < 45) return "刚刚";
  if (absSeconds < 3600) return ZH_RELATIVE.format(Math.round(diffSeconds / 60), "minute");
  if (absSeconds < 86400) return ZH_RELATIVE.format(Math.round(diffSeconds / 3600), "hour");
  if (absSeconds < 2592000) return ZH_RELATIVE.format(Math.round(diffSeconds / 86400), "day");
  return formatAbsoluteTime(value);
}

export function shortId(value?: string | null, length = 8) {
  return value ? `${value.slice(0, length)}${value.length > length ? "..." : ""}` : "-";
}

export function formatDuration(seconds?: number | null) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "-";
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes === 0) return `${rest} 秒`;
  return `${minutes} 分 ${rest.toString().padStart(2, "0")} 秒`;
}
