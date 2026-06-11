import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { RequireAuth } from "./components/RequireAuth";
import LoginPage from "./pages/auth/LoginPage";
import CaseListPage from "./pages/studio/CaseListPage";
import StudioCreatePage from "./pages/studio/StudioCreatePage";
import RunsPage from "./pages/studio/RunsPage";
import FinishedVideosPage from "./pages/studio/FinishedVideosPage";
import SettingsPage from "./pages/settings/SettingsPage";
import PlaceholderPage from "./pages/PlaceholderPage";
import { routePatterns, routes } from "./routes";

export default function App() {
  return (
    <Routes>
      <Route path={routePatterns.login} element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route index element={<Navigate to={routes.studio()} replace />} />
          <Route path={routePatterns.studio} element={<CaseListPage />} />
          <Route path={routePatterns.caseStudio} element={<StudioCreatePage />} />
          <Route path={routePatterns.caseRuns} element={<RunsPage />} />
          <Route path={routePatterns.caseFinishedVideos} element={<FinishedVideosPage />} />
          <Route path={routePatterns.casePublish} element={<PlaceholderPage title="发布中心" />} />
          <Route path={routePatterns.settings} element={<SettingsPage />} />
          <Route path={routePatterns.library} element={<PlaceholderPage title="素材库" />} />
          <Route path={routePatterns.ops} element={<PlaceholderPage title="Ops" />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to={routes.studio()} replace />} />
    </Routes>
  );
}
