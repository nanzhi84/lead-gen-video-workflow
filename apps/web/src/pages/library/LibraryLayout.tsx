import { NavLink, Navigate, useLocation } from "react-router-dom";
import { libraryTabs, readTab } from "../../components/library/libraryModel";
import { AISourceTab } from "./AISourceTab";
import { BgmTab } from "./BgmTab";
import { FontsTab } from "./FontsTab";
import { TemplatesTab } from "./TemplatesTab";
import { VoicesTab } from "./VoicesTab";

export default function LibraryLayout() {
  const location = useLocation();
  const tab = readTab(location.pathname);

  if (!tab) return <Navigate to="/library/voices" replace />;

  return (
    <div className="pageStack">
      <header className="pageHeader">
        <div>
          <h1>素材库</h1>
          <p className="mt-2 text-sm text-text-secondary">管理音色、视频模板、AI素材、字体与配乐素材。</p>
        </div>
      </header>

      <nav className="tabs" aria-label="素材库分类">
        {libraryTabs.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink key={item.id} to={item.to} className={({ isActive }) => `tabLink ${isActive ? "active" : ""}`}>
              <Icon className="h-4 w-4" />
              <span>{item.label}</span>
            </NavLink>
          );
        })}
      </nav>

      {tab === "voices" ? <VoicesTab /> : null}
      {tab === "templates" ? <TemplatesTab /> : null}
      {tab === "ai_source" ? <AISourceTab /> : null}
      {tab === "fonts" ? <FontsTab /> : null}
      {tab === "bgm" ? <BgmTab /> : null}
    </div>
  );
}
