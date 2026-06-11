export default function PlaceholderPage({ title }: { title: string }) {
  return (
    <section className="pageStack">
      <div className="pageHeader">
        <div>
          <h1>{title}</h1>
          <p>建设中，M6a-2 继续展开。</p>
        </div>
      </div>
      <div className="skeletonGrid">
        <div />
        <div />
        <div />
      </div>
    </section>
  );
}
