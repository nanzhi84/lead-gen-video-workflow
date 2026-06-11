export function AudioPlayer({ src, title = "音频预览" }: { src: string; title?: string }) {
  return (
    <figure className="grid gap-2 rounded-2xl border border-border bg-white/60 p-3">
      <figcaption className="text-sm font-medium text-text-primary">{title}</figcaption>
      <audio src={src} controls className="w-full" />
    </figure>
  );
}
