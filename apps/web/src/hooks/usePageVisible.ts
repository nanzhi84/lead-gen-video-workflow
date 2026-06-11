import { useEffect, useState } from "react";

function readVisible() {
  return typeof document === "undefined" ? true : !document.hidden;
}

export function usePageVisible() {
  const [visible, setVisible] = useState(readVisible);

  useEffect(() => {
    const handleVisibility = () => setVisible(readVisible());
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, []);

  return visible;
}
