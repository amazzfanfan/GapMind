import { useCallback, useEffect, useState } from "react";
import { App, Button, Card, Empty, List, Progress, Space, Spin, Statistic, Tabs, Tag, Typography } from "antd";
import { BulbOutlined, ExperimentOutlined, FileDoneOutlined, ReloadOutlined, RobotOutlined } from "@ant-design/icons";
import { Link } from "react-router-dom";
import { discoverApi, type OpportunityPortfolioItem, type ResearchPlan } from "../api/discover";
import { useWorkspaceLayout } from "../components/layout/WorkspaceLayout";

const { Paragraph, Text, Title } = Typography;

function errorMessage(error: unknown): string {
  const response = error as { response?: { data?: { detail?: { message?: string } } } };
  return response.response?.data?.detail?.message || (error as Error).message || "请求失败";
}

export default function ResearchPlansPage() {
  const { workspace } = useWorkspaceLayout();
  const { message } = App.useApp();
  const [portfolio, setPortfolio] = useState<OpportunityPortfolioItem[]>([]);
  const [plans, setPlans] = useState<ResearchPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [convertingId, setConvertingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [opportunityResponse, planResponse] = await Promise.all([
        discoverApi.listConfirmedPortfolio(workspace.id, { limit: 100 }),
        discoverApi.listPlans(workspace.id, { limit: 100 }),
      ]);
      setPortfolio(opportunityResponse.items);
      setPlans(planResponse.items);
    } catch (error) {
      message.error(`研究中心加载失败：${errorMessage(error)}`);
    } finally {
      setLoading(false);
    }
  }, [message, workspace.id]);

  useEffect(() => { void load(); }, [load]);

  const generatePlan = async (item: OpportunityPortfolioItem) => {
    setConvertingId(item.opportunity.id);
    try {
      await discoverApi.convert(workspace.id, item.opportunity.id);
      message.success("研究计划已生成");
      await load();
    } catch (error) {
      message.error(`计划生成失败：${errorMessage(error)}`);
    } finally {
      setConvertingId(null);
    }
  };

  const opportunityContent = portfolio.length ? (
    <List
      grid={{ gutter: 16, xs: 1, sm: 1, md: 2, xl: 2, xxl: 3 }}
      dataSource={portfolio}
      renderItem={(item) => {
        const version = item.current_version;
        return (
          <List.Item>
            <Card
              style={{ height: "100%" }}
              title={<Space wrap><BulbOutlined /><Text strong>{item.opportunity.title}</Text></Space>}
              extra={<Tag color="green">已确认</Tag>}
              actions={[
                <Link key="detail" to={`/workspaces/${workspace.id}/discover/opportunities/${item.opportunity.id}`}>查看证据</Link>,
                item.plan
                  ? <Text key="created" type="success">计划已生成</Text>
                  : <Button key="plan" type="link" loading={convertingId === item.opportunity.id} onClick={() => void generatePlan(item)}>生成研究计划</Button>,
              ]}
            >
              <Paragraph ellipsis={{ rows: 3 }}>{version?.problem_statement || item.opportunity.summary}</Paragraph>
              <Space direction="vertical" size={6} style={{ width: "100%" }}>
                <Text type="secondary">研究问题</Text>
                <Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 4 }}>{version?.candidate_research_question || "尚未形成结构化研究问题"}</Paragraph>
                <Space wrap>
                  <Tag>Agent confidence {Math.round(item.opportunity.confidence * 100)}%</Tag>
                  <Tag color={version?.verification_status === "verified" ? "green" : "orange"}>{version?.verification_status || "未验证"}</Tag>
                </Space>
                <Progress size="small" percent={Math.round((version?.evidence_coverage || 0) * 100)} format={(value) => `证据覆盖 ${value}%`} />
              </Space>
            </Card>
          </List.Item>
        );
      }}
    />
  ) : <Empty description="还没有已确认的研究机会" image={Empty.PRESENTED_IMAGE_SIMPLE}><Link to={`/workspaces/${workspace.id}/discover`}><Button type="primary">前往 Discover</Button></Link></Empty>;

  const planContent = plans.length ? (
    <List
      dataSource={plans}
      renderItem={(plan) => (
        <List.Item>
          <List.Item.Meta
            avatar={<FileDoneOutlined style={{ fontSize: 22, color: "#1677ff" }} />}
            title={<Space wrap><Text strong>{plan.research_question}</Text><Tag color="blue">{plan.status}</Tag></Space>}
            description={<Space direction="vertical" size={4}><Text>假设：{plan.hypothesis || "—"}</Text><Space wrap>{plan.datasets.slice(0, 4).map((dataset) => <Tag key={dataset}>{dataset}</Tag>)}<Text type="secondary">{plan.validation_steps.length} 个验证步骤</Text></Space></Space>}
          />
          <Link to={`/workspaces/${workspace.id}/discover/opportunities/${plan.opportunity_id}`}><Button>查看来源机会</Button></Link>
        </List.Item>
      )}
    />
  ) : <Empty description="已确认机会生成计划后，会固定收纳在这里" image={Empty.PRESENTED_IMAGE_SIMPLE} />;

  return (
    <Space direction="vertical" size={16} style={{ width: "100%", padding: "20px 8px 32px" }}>
      <Space align="start" style={{ width: "100%", justifyContent: "space-between" }} wrap>
        <div><Title level={2} style={{ margin: 0 }}>研究中心</Title><Text type="secondary">将已确认的研究机会沉淀为计划，并作为后续深度研究 Agent 的可靠输入。</Text></div>
        <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>刷新</Button>
      </Space>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
        <Card size="small"><Statistic title="已确认机会" value={portfolio.length} prefix={<BulbOutlined />} /></Card>
        <Card size="small"><Statistic title="研究计划" value={plans.length} prefix={<ExperimentOutlined />} /></Card>
        <Card size="small"><Statistic title="Agent 可用计划" value={plans.length} prefix={<RobotOutlined />} /></Card>
      </div>
      <Card bodyStyle={{ paddingTop: 8 }}>
        {loading && !portfolio.length && !plans.length ? <div className="gm-loading"><Spin tip="正在加载研究资产" /></div> : (
          <Tabs
            items={[
              { key: "opportunities", label: `已确认机会 (${portfolio.length})`, children: opportunityContent },
              { key: "plans", label: `研究计划 (${plans.length})`, children: planContent },
              { key: "deep-research", label: "深度研究", children: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="下一阶段将在这里启动和跟踪深度研究 Agent"><Text type="secondary">Agent 将绑定确认时的 Opportunity Version 和研究计划，避免输入随后续编辑漂移。</Text></Empty> },
            ]}
          />
        )}
      </Card>
    </Space>
  );
}
