import { App, Button, Card, Col, Row, Space, Tag, Typography } from "antd";
import {
  ArrowRightOutlined,
  BulbOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
  FundProjectionScreenOutlined,
  SafetyCertificateOutlined,
  SendOutlined,
} from "@ant-design/icons";
import { useNavigate } from "react-router-dom";

/**
 * P1.5: research-lifecycle module entry cards (Discover → Plan → Execute →
 * Analyze → Publish → Respond), mirroring the standalone index.html overview.
 *
 * 2026-08-20: stage direct-entry. Corpus-bound modules (Discover / Plan /
 * Execute) require a workspace; the user-material modules (Analyze / Publish /
 * Respond) deep-link into the assistant with their mode preselected — with a
 * workspace for evidence grounding, or standalone (independent mode) without.
 */

interface LifecycleModule {
  key: string;
  title: string;
  subtitle: string;
  description: string;
  icon: React.ReactNode;
  workspaceBound: boolean;
}

const MODULES: LifecycleModule[] = [
  { key: "discover", title: "Discover", subtitle: "研究机会发现", description: "多智能体协同，从证据链发现可验证的研究缺口", icon: <BulbOutlined />, workspaceBound: true },
  { key: "plan", title: "Plan", subtitle: "研究计划", description: "生成可证伪、回链证据的研究计划，人工确认后落库", icon: <ExperimentOutlined />, workspaceBound: true },
  { key: "execute", title: "Execute", subtitle: "代码生成", description: "基于计划生成可复现的实验代码项目，可预览/下载", icon: <FundProjectionScreenOutlined />, workspaceBound: true },
  { key: "analyze", title: "Analyze", subtitle: "结果分析", description: "对照证伪标准分析实验结果，判定支持/否定", icon: <FileSearchOutlined />, workspaceBound: false },
  { key: "publish", title: "Publish", subtitle: "论文写作", description: "基于计划与证据生成论文章节草稿", icon: <SafetyCertificateOutlined />, workspaceBound: false },
  { key: "respond", title: "Respond", subtitle: "审稿回复", description: "逐条回应审稿意见，依据回链证据", icon: <SendOutlined />, workspaceBound: false },
];

// module key -> assistant ChatMode for direct entry (user-material modules)
const MODE_BY_KEY: Record<string, "analyze" | "write" | "respond"> = {
  analyze: "analyze",
  publish: "write",
  respond: "respond",
};

export default function LifecycleModules({ workspaceId }: { workspaceId?: string }) {
  const navigate = useNavigate();
  const { message } = App.useApp();

  const openModule = (module: LifecycleModule) => {
    if (module.key === "discover" || module.key === "plan") {
      // Corpus-bound modules need a workspace (paper evidence).
      if (!workspaceId) {
        message.info("研究机会发现/研究计划需要课题空间（论文语料）");
        navigate("/workspaces");
        return;
      }
      navigate(module.key === "discover" ? `/workspaces/${workspaceId}/discover` : `/workspaces/${workspaceId}/plans`);
      return;
    }
    if (module.key === "execute") {
      // code generation requires a confirmed research plan (workspace-bound)
      if (!workspaceId) {
        message.info("代码生成需要课题空间中的研究计划");
        navigate("/workspaces");
        return;
      }
      navigate(`/workspaces/${workspaceId}/assistant?mode=code_generation`);
      return;
    }
    // user-material modules: direct entry with the mode preselected;
    // standalone (independent mode) when no workspace is picked
    const mode = MODE_BY_KEY[module.key];
    navigate(workspaceId ? `/workspaces/${workspaceId}/assistant?mode=${mode}` : `/chat/new?mode=${mode}`);
  };

  return (
    <Card
      className="gm-section-card"
      title="研究生命周期模块"
      style={{ marginTop: 16 }}
    >
      <Row gutter={[12, 12]}>
        {MODULES.map((module) => (
          <Col xs={12} sm={8} lg={4} key={module.key}>
            <Card
              hoverable
              className="gm-lifecycle-module"
              onClick={() => openModule(module)}
              bodyStyle={{ padding: 14, minHeight: 132 }}
            >
              <Space direction="vertical" size={6} style={{ width: "100%" }}>
                <div className="gm-lifecycle-module-icon">{module.icon}</div>
                <div>
                  <Typography.Text strong style={{ fontSize: 15 }}>{module.title}</Typography.Text>
                  <div><Typography.Text type="secondary" style={{ fontSize: 12 }}>{module.subtitle}</Typography.Text></div>
                </div>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>{module.description}</Typography.Text>
                <div>{module.workspaceBound ? <Tag style={{ marginInlineEnd: 0 }}>需课题空间</Tag> : <Tag color="green" style={{ marginInlineEnd: 0 }}>可独立使用</Tag>}</div>
                <Button type="link" size="small" style={{ padding: 0 }} icon={<ArrowRightOutlined />}>
                  {workspaceId || !module.workspaceBound ? "进入" : "选择课题空间"}
                </Button>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>
    </Card>
  );
}
