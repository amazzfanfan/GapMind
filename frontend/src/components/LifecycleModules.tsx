import { Button, Card, Col, Row, Space, Tag, Typography } from "antd";
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
 * Each module works as an independent entry point; workspace-bound modules
 * (Discover / Plan) ask the user to pick a workspace first.
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
  { key: "analyze", title: "Analyze", subtitle: "结果分析", description: "对照证伪标准分析实验结果，判定支持/否定", icon: <FileSearchOutlined />, workspaceBound: true },
  { key: "publish", title: "Publish", subtitle: "论文写作", description: "基于计划与证据生成论文章节草稿", icon: <SafetyCertificateOutlined />, workspaceBound: true },
  { key: "respond", title: "Respond", subtitle: "审稿回复", description: "逐条回应审稿意见，依据回链证据", icon: <SendOutlined />, workspaceBound: true },
];

export default function LifecycleModules({ workspaceId }: { workspaceId?: string }) {
  const navigate = useNavigate();

  const openModule = (module: LifecycleModule) => {
    if (!workspaceId) {
      navigate("/workspaces");
      return;
    }
    if (module.key === "discover") navigate(`/workspaces/${workspaceId}/discover`);
    else if (module.key === "plan") navigate(`/workspaces/${workspaceId}/plans`);
    else navigate(`/workspaces/${workspaceId}/assistant`);
  };

  return (
    <Card
      className="gm-section-card"
      title="研究生命周期模块"
      extra={!workspaceId ? <Tag color="blue">请先选择课题空间</Tag> : undefined}
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
                <Button type="link" size="small" style={{ padding: 0 }} icon={<ArrowRightOutlined />}>
                  进入
                </Button>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>
    </Card>
  );
}
