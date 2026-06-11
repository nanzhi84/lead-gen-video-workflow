import { Edit3, Film, RadioTower } from "lucide-react";
import { NavLink } from "react-router-dom";
import { routes } from "../routes";

export function StudioTabs({ caseId }: { caseId: string }) {
  const tabs = [
    { to: routes.caseStudio(caseId), label: "创作", icon: Edit3, end: true },
    { to: routes.caseRuns(caseId), label: "Runs", icon: RadioTower },
    { to: routes.caseFinishedVideos(caseId), label: "成片", icon: Film },
  ];
  return (
    <nav className="tabs" aria-label="Case 工作台">
      {tabs.map((tab) => {
        const Icon = tab.icon;
        return (
          <NavLink className="tabLink" to={tab.to} end={tab.end} key={tab.to}>
            <Icon size={15} />
            <span>{tab.label}</span>
          </NavLink>
        );
      })}
    </nav>
  );
}
