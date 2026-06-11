export default function PlaceholderPage({ title }: { title: string }) {
  return (
    <section className="pageStack">
      <div className="pageHeader">
        <div>
          <h1>{title}</h1>
          <p>建设中，后续里程碑继续展开。</p>
        </div>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <div className="card grid gap-3">
          <div className="h-4 w-24 rounded-full bg-surface-hover" />
          <div className="h-16 rounded-2xl bg-white/60" />
        </div>
        <div className="card grid gap-3">
          <div className="h-4 w-28 rounded-full bg-surface-hover" />
          <div className="h-16 rounded-2xl bg-white/60" />
        </div>
        <div className="card grid gap-3">
          <div className="h-4 w-20 rounded-full bg-surface-hover" />
          <div className="h-16 rounded-2xl bg-white/60" />
        </div>
      </div>
    </section>
  );
}
