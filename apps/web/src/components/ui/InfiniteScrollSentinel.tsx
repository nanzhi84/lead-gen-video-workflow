import { useEffect, useRef } from "react";

type InfiniteScrollSentinelProps = {
  enabled: boolean;
  onVisible: () => void;
  label?: string;
};

export function InfiniteScrollSentinel({ enabled, onVisible, label = "继续加载" }: InfiniteScrollSentinelProps) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!enabled || !ref.current) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) onVisible();
    });
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, [enabled, onVisible]);

  return (
    <div ref={ref} className="py-3 text-center text-xs text-text-tertiary">
      {enabled ? label : "没有更多了"}
    </div>
  );
}
