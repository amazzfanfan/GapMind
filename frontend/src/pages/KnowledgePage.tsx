import { lazy, Suspense } from "react";
import { Tabs, Typography } from "antd";
import { useNavigate } from "react-router-dom";
import KnowledgeWorkbench from "../components/KnowledgeWorkbench";
import { useWorkspaceLayout } from "../components/layout/WorkspaceLayout";

const KnowledgeGraph = lazy(() => import("../components/KnowledgeGraph"));

const { Paragraph, Title } = Typography;

export default function KnowledgePage({
  initialTab = "workbench",
}: {
  initialTab?: "workbench" | "graph";
}) {
  const navigate = useNavigate();
  const { workspace } = useWorkspaceLayout();

  const activeKey = initialTab;
  return (
    <div>
      <Title level={3} style={{ marginBottom: 4 }}>
        {activeKey === "graph" ? "知识图谱" : "知识工作台"}
      </Title>
      <Paragraph type="secondary">
        {activeKey === "graph"
          ? "从研究全景、观点关系和证据溯源三个视角探索课题知识。"
          : "审核 AI 从论文中提取的知识，回到证据原文，并探索课题内的关系。"}
      </Paragraph>

      <Tabs
        activeKey={activeKey}
        onChange={(key) => {
          navigate(
            key === "graph"
              ? `/workspaces/${workspace.id}/knowledge/graph`
              : `/workspaces/${workspace.id}/knowledge`,
          );
        }}
        items={[
          {
            key: "workbench",
            label: "审核工作台",
            children: <KnowledgeWorkbench workspaceId={workspace.id} />,
          },
          {
            key: "graph",
            label: "知识图谱",
            children: (
              <div className="gm-knowledge-graph-bleed">
                <Suspense fallback={<div style={{ padding: 48, textAlign: "center" }}>Loading graph…</div>}>
                  <KnowledgeGraph workspaceId={workspace.id} />
                </Suspense>
              </div>
            ),
          },
        ]}
      />
    </div>
  );
}
