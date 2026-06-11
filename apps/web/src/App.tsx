import { NavLink, Route, Routes } from "react-router-dom";
import { Boxes, BrainCircuit, BriefcaseBusiness, Clapperboard, Gauge, KeyRound, Library, RadioTower } from "lucide-react";
import CasesPage from "./pages/CasesPage";
import StudioPage from "./pages/StudioPage";
import AssetsPage from "./pages/AssetsPage";
import PublishPage from "./pages/PublishPage";
import OpsPage from "./pages/OpsPage";
import SettingsPage from "./pages/SettingsPage";

const nav = [
  { to: "/", label: "Cases", icon: BriefcaseBusiness },
  { to: "/studio", label: "Studio", icon: BrainCircuit },
  { to: "/runs", label: "Runs", icon: RadioTower },
  { to: "/assets", label: "Assets", icon: Library },
  { to: "/publish", label: "Publish", icon: Clapperboard },
  { to: "/ops", label: "Ops", icon: Gauge },
  { to: "/settings", label: "Settings", icon: KeyRound },
];

function Shell() {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <Boxes size={22} />
          <span>Cutagent</span>
        </div>
        <nav className="nav">
          {nav.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink key={item.to} to={item.to} end={item.to === "/"} className="navItem">
                <Icon size={18} />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<CasesPage />} />
          <Route path="/studio" element={<StudioPage />} />
          <Route path="/runs" element={<OpsPage mode="runs" />} />
          <Route path="/assets" element={<AssetsPage />} />
          <Route path="/publish" element={<PublishPage />} />
          <Route path="/ops" element={<OpsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}

export default Shell;

