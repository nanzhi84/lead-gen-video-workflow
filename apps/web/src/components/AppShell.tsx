import {
  Boxes,
  BriefcaseBusiness,
  Clapperboard,
  Gauge,
  KeyRound,
  Library,
  LogOut,
  Video,
} from "lucide-react";
import { NavLink, Outlet, useLocation, useParams } from "react-router-dom";
import { routes } from "../routes";
import { useAuth } from "../pages/auth/AuthContext";

const mainNav = [
  { to: routes.studio(), label: "Cases", icon: BriefcaseBusiness },
  { to: routes.library(), label: "素材库", icon: Library },
  { to: routes.casePublish("__placeholder__"), label: "发布", icon: Clapperboard, disabled: true },
  { to: routes.ops(), label: "Ops", icon: Gauge },
  { to: routes.settings(), label: "设置", icon: KeyRound },
];

function Breadcrumbs() {
  const location = useLocation();
  const params = useParams();
  const parts = ["工作台"];
  if (location.pathname.startsWith("/studio")) {
    parts.push(params.caseId ? "Case" : "Cases");
  }
  if (location.pathname.endsWith("/runs")) {
    parts.push("Runs");
  } else if (location.pathname.endsWith("/finished-videos")) {
    parts.push("成片");
  } else if (location.pathname.startsWith("/settings")) {
    parts.push("设置");
  } else if (location.pathname.startsWith("/library")) {
    parts.push("素材库");
  } else if (location.pathname.startsWith("/ops")) {
    parts.push("Ops");
  }
  return <div className="breadcrumbs">{parts.join(" / ")}</div>;
}

export function AppShell() {
  const { user, logout } = useAuth();
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <Boxes size={21} />
          <div>
            <strong>Cutagent</strong>
            <span>Case Studio</span>
          </div>
        </div>
        <nav className="nav" aria-label="主导航">
          {mainNav.map((item) => {
            const Icon = item.icon;
            if (item.disabled) {
              return (
                <span className="navItem disabled" key={item.label} title="进入 Case 后可用">
                  <Icon size={17} />
                  <span>{item.label}</span>
                </span>
              );
            }
            return (
              <NavLink className="navItem" key={item.to} to={item.to}>
                <Icon size={17} />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>
        <div className="sidebarFooter">
          <div className="userPill">
            <Video size={15} />
            <span>{user?.display_name ?? user?.email}</span>
            <b>{user?.role}</b>
          </div>
          <button className="ghostButton full" type="button" onClick={() => void logout()}>
            <LogOut size={15} />
            <span>退出登录</span>
          </button>
        </div>
      </aside>
      <main className="main">
        <Breadcrumbs />
        <Outlet />
      </main>
    </div>
  );
}
