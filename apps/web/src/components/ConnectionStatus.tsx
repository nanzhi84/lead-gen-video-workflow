import { Wifi, WifiOff } from "lucide-react";
import { useEffect, useState } from "react";

function getVisible() {
  return typeof document === "undefined" ? true : !document.hidden;
}

function getOnline() {
  return typeof navigator === "undefined" ? true : navigator.onLine;
}

export function ConnectionStatus() {
  const [online, setOnline] = useState(getOnline);
  const [visible, setVisible] = useState(getVisible);

  useEffect(() => {
    const handleOnline = () => setOnline(true);
    const handleOffline = () => setOnline(false);
    const handleVisibility = () => setVisible(getVisible());
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, []);

  const healthy = online && visible;
  const Icon = online ? Wifi : WifiOff;
  return (
    <div
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium ${
        healthy
          ? "border-status-success/20 bg-status-success/10 text-status-success"
          : "border-status-warning/25 bg-status-warning/10 text-status-warning"
      }`}
      title={online ? "网络在线" : "浏览器离线"}
    >
      <Icon className="h-3.5 w-3.5" />
      <span>{online ? (visible ? "实时连接待命" : "页面后台暂停轮询") : "网络离线"}</span>
    </div>
  );
}
