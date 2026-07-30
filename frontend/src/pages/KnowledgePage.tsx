import { lazy, Suspense, useEffect, useState } from "react";
import { App, Button, Card, Spin, Tabs, Typography } from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { Link, useNavigate, useParams } from "react-router-dom";
import workspaceApi from "../api/workspace";
import type { Workspace } from "../api/types/workspace";
import KnowledgeWorkbench from "../components/KnowledgeWorkbench";

const KnowledgeGraph = lazy(() => import("../components/KnowledgeGraph"));

const { Paragraph, Title } = Typography;

export default function KnowledgePage({
  initialTab = "workbench",
}: {
  initialTab?: "workbench" | "graph";
}) {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    workspaceApi
      .get(id)
      .then(setWorkspace)
      .catch((error) => message.error(`Failed to load workspace: ${(error as Error).message}`))
      .finally(() => setLoading(false));
  }, [id, message]);

  if (loading) {
    return <div style={{ padding: 48, textAlign: "center" }}><Spin /></div>;
  }

  if (!id || !workspace) {
    return (
      <Card>
        <Title level={4}>Workspace not found</Title>
        <Link to="/workspaces">Back to workspaces</Link>
      </Card>
    );
  }

  const activeKey = initialTab;
  return (
    <div>
      <Button
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate(`/workspaces/${workspace.id}`)}
        style={{ marginBottom: 16 }}
      >
        Back to workspace
      </Button>
      <Title level={3} style={{ marginBottom: 4 }}>{workspace.name} · Knowledge</Title>
      <Paragraph type="secondary">
        Review AI-extracted knowledge, trace it back to evidence, and explore relationships within this Workspace.
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
            label: "Workbench",
            children: <KnowledgeWorkbench workspaceId={workspace.id} />,
          },
          {
            key: "graph",
            label: "Knowledge Graph",
            children: (
              <Suspense fallback={<div style={{ padding: 48, textAlign: "center" }}>Loading graph…</div>}>
                <KnowledgeGraph workspaceId={workspace.id} />
              </Suspense>
            ),
          },
        ]}
      />
    </div>
  );
}
