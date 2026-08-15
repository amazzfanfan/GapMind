import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import WorkspaceLayout from "./components/layout/WorkspaceLayout";
import DashboardPage from "./pages/DashboardPage";
import SearchPage from "./pages/SearchPage";
import WorkspacesPage from "./pages/WorkspacesPage";
import WorkspaceOverviewPage from "./pages/WorkspaceOverviewPage";
import WorkspacePapersPage from "./pages/WorkspacePapersPage";
import WorkspaceActivityPage from "./pages/WorkspaceActivityPage";
import WorkspaceSettingsPage from "./pages/WorkspaceSettingsPage";
import ResearchPlansPage from "./pages/ResearchPlansPage";
import NotFoundPage from "./pages/NotFoundPage";
import ReadingPage from "./pages/ReadingPage";
import ReadingPaperPage from "./pages/ReadingPaperPage";

const KnowledgePage = lazy(() => import("./pages/KnowledgePage"));
const DiscoverPage = lazy(() => import("./pages/DiscoverPage"));
const GapBoardPage = lazy(() => import("./pages/GapBoardPage"));
const ChatPage = lazy(() => import("./pages/ChatPage"));
const ChatHubPage = lazy(() => import("./pages/ChatHubPage"));

function LazyPage({ children, label }: { children: ReactNode; label: string }) {
  return <Suspense fallback={<div className="gm-loading">正在加载{label}…</div>}>{children}</Suspense>;
}

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/chat" element={<LazyPage label="AI 助手"><ChatHubPage /></LazyPage>} />
        <Route path="/chat/new" element={<LazyPage label="通用对话"><ChatPage /></LazyPage>} />
        <Route path="/chat/:conversationId" element={<LazyPage label="AI 对话"><ChatPage /></LazyPage>} />
        <Route path="/reading" element={<ReadingPage />} />
        <Route path="/reading/:paperId" element={<ReadingPaperPage />} />
        <Route path="/workspaces" element={<WorkspacesPage />} />
        <Route path="/workspaces/:id" element={<WorkspaceLayout />}>
          <Route index element={<Navigate to="overview" replace />} />
          <Route path="overview" element={<WorkspaceOverviewPage />} />
          <Route path="papers" element={<WorkspacePapersPage />} />
          <Route path="assistant" element={<LazyPage label="AI 助手"><ChatPage /></LazyPage>} />
          <Route path="assistant/:conversationId" element={<LazyPage label="AI 助手"><ChatPage /></LazyPage>} />
          <Route path="knowledge" element={<LazyPage label="知识"><KnowledgePage /></LazyPage>} />
          <Route path="knowledge/graph" element={<LazyPage label="知识图谱"><KnowledgePage initialTab="graph" /></LazyPage>} />
          <Route path="discover" element={<LazyPage label="Discover"><DiscoverPage /></LazyPage>} />
          <Route path="gap-board" element={<LazyPage label="研究空白棋盘"><GapBoardPage /></LazyPage>} />
          <Route path="discover/runs/:runId" element={<LazyPage label="Discover 运行"><DiscoverPage /></LazyPage>} />
          <Route path="discover/opportunities/:opportunityId" element={<LazyPage label="研究机会"><DiscoverPage /></LazyPage>} />
          <Route path="plans" element={<ResearchPlansPage />} />
          <Route path="activity" element={<WorkspaceActivityPage />} />
          <Route path="settings" element={<WorkspaceSettingsPage />} />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
