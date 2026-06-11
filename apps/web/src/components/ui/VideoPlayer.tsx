export function VideoPlayer({ src, title = "视频预览" }: { src: string; title?: string }) {
  return (
    <figure className="grid gap-2 rounded-[24px] border border-border bg-white/60 p-3">
      <figcaption className="text-sm font-medium text-text-primary">{title}</figcaption>
      <video src={src} controls className="aspect-[9/16] max-h-[70vh] rounded-2xl bg-[#111] object-contain" />
    </figure>
  );
}
