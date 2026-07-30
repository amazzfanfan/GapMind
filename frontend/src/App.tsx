import { lazy, Suspense } from "react";
import { Routes, Route } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import DashboardPage from "./pages/DashboardPage";
import SearchPage from "./pages/SearchPage";
import WorkspacesPage from "./pages/WorkspacesPage";
import WorkspaceDetailPage from "./pages/WorkspaceDetailPage";
import NotFoundPage from "./pages/NotFoundPage";

const KnowledgePage = lazy(() => import("./pages/KnowledgePage"));
const DiscoverPage = lazy(() => import("./pages/DiscoverPage"));

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/workspaces" element={<WorkspacesPage />} />
        <Route path="/workspaces/:id" element={<WorkspaceDetailPage />} />
        <Route
          path="/workspaces/:id/knowledge"
          element={<Suspense fallback={<div style={{ padding: 48 }}>Loading knowledge…</div>}><KnowledgePage /></Suspense>}
        />
        <Route
          path="/workspaces/:id/discover"
          element={<Suspense fallback={<div style={{ padding: 48 }}>Loading Discover…</div>}><DiscoverPage /></Suspense>}
        />
        <Route
          path="/workspaces/:id/knowledge/graph"
          element={<Suspense fallback={<div style={{ padding: 48 }}>Loading knowledge graph…</div>}><KnowledgePage initialTab="graph" /></Suspense>}
        />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
