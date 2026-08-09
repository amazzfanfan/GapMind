import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  List,
  Modal,
  Progress,
  Space,
  Spin,
  Statistic,
  Steps,
  Tabs,
  Tag,
  Typography,
} from "antd";
import {
  BulbOutlined,
  CheckCircleOutlined,
  ExperimentOutlined,
  FileDoneOutlined,
  ReloadOutlined,
  RobotOutlined,
  SearchOutlined,
  StopOutlined,
} from "@ant-design/icons";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import "katex/dist/katex.min.css";
import agentApi, { type AgentRun, type AgentRunDetail } from "../api/agent";
import chatApi from "../api/chat";
import { discoverApi, type OpportunityPortfolioItem, type ResearchPlan } from "../api/discover";
import { useWorkspaceLayout } from "../components/layout/WorkspaceLayout";

const { Paragraph, Text, Title } = Typography;

const stageLabels: Record<string, string> = {
  queued: "等待执行",
  preflight: "输入检查",
  plan_binding: "固定计划快照",
  workspace_retrieval: "检索工作区证据",
  evidence_collection: "汇集核验证据",
  deep_synthesis: "深度综合",
  evidence_gate: "证据引用检查",
  human_review: "等待人工审核",
  saved: "已确认保存",
  failed: "执行失败",
  cancelled: "已取消",
};

function errorMessage(error: unknown): string {
  const response = error as { response?: { data?: { detail?: { message?: string } } } };
  return response.response?.data?.detail?.message || (error as Error).message || "请求失败";
}

function values(values: string[]): string {
  return values.length ? values.join("；") : "—";
}

export function normalizeMathMarkdown(content: string): string {
  const fencedMath = content.replace(/```math\s*\n([\s\S]*?)```/g, (_match, formula: string) => `\n$$\n${formula.trim()}\n$$\n`);
  const normalizedObjective = fencedMath.replace(/(#{2,4}\s+优化目标\s*\n+)(?!\$\$)([^\n]+)/g, (_match, heading: string, line: string) => {
    if (!/[=+*^]|MMD|LPIPS|loss|mathcal/i.test(line)) return `${heading}${line}`;
    const split = line.match(/^(.*?)([，。]\s*其中.*)$/);
    const formula = objectiveFormulaToLatex((split?.[1] || line).trim());
    const explanation = split?.[2]?.replace(/^[，。]\s*/, "") || "";
    return `${heading}$$\n${formula}\n$$${explanation ? `\n\n${explanation}` : ""}`;
  });
  return normalizeInlineMathVariables(normalizedObjective);
}

export function normalizeInlineMathVariables(content: string): string {
  let inDisplayMath = false;
  let inCodeFence = false;

  return content
    .split("\n")
    .map((line) => {
      const trimmed = line.trim();
      if (trimmed.startsWith("```")) {
        inCodeFence = !inCodeFence;
        return line;
      }
      if (!inCodeFence && trimmed === "$$") {
        inDisplayMath = !inDisplayMath;
        return line;
      }
      if (inCodeFence || inDisplayMath) return line;

      return line.replace(
        /(^|[^$`\\])\b([A-Za-z](?:['′])?)_([A-Za-z][A-Za-z0-9]*|\d+)\b/g,
        (_match, prefix: string, base: string, subscript: string) => {
          const latexSubscript = subscript.length === 1 ? subscript : `\\mathrm{${subscript}}`;
          return `${prefix}$${base}_{${latexSubscript}}$`;
        },
      );
    })
    .join("\n");
}

export function objectiveFormulaToLatex(value: string): string {
  return value
    .replace(/λ\s*(\d+)/g, "\\lambda_{$1}")
    .replace(/β\s*(\d+)/g, "\\beta_{$1}")
    .replace(/λ/g, "\\lambda")
    .replace(/β/g, "\\beta")
    .replace(/\bMMD(?=\()/g, "\\operatorname{MMD}")
    .replace(/\bLPIPS(?=\()/g, "\\operatorname{LPIPS}")
    .replace(/\bCausal_loss(?=\()/g, "\\mathcal{L}_{\\mathrm{causal}}")
    .replace(/\s*\*\s*/g, " \\cdot ")
    .replace(/([A-Za-z])_([A-Za-z]+)/g, "$1_{\\mathrm{$2}}");
}

export default function ResearchPlansPage() {
  const { workspace } = useWorkspaceLayout();
  const { message, modal } = App.useApp();
  const [portfolio, setPortfolio] = useState<OpportunityPortfolioItem[]>([]);
  const [plans, setPlans] = useState<ResearchPlan[]>([]);
  const [deepRuns, setDeepRuns] = useState<AgentRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionId, setActionId] = useState<string | null>(null);
  const [selectedPlan, setSelectedPlan] = useState<ResearchPlan | null>(null);
  const [selectedRun, setSelectedRun] = useState<AgentRunDetail | null>(null);
  const [reportLoading, setReportLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      const [opportunityResponse, planResponse, runResponse] = await Promise.all([
        discoverApi.listConfirmedPortfolio(workspace.id, { limit: 100 }),
        discoverApi.listPlans(workspace.id, { limit: 100 }),
        agentApi.list(workspace.id, { limit: 100 }),
      ]);
      setPortfolio(opportunityResponse.items);
      setPlans(planResponse.items);
      setDeepRuns(runResponse.items.filter((item) => item.agent_type === "deep_research"));
    } catch (error) {
      message.error(`研究中心加载失败：${errorMessage(error)}`);
    } finally {
      setLoading(false);
    }
  }, [message, workspace.id]);

  useEffect(() => { void load(); }, [load]);
  const hasActiveRun = deepRuns.some((run) => ["queued", "running"].includes(run.status));
  useEffect(() => {
    if (!hasActiveRun) return;
    const timer = window.setInterval(() => void load(), 2200);
    return () => window.clearInterval(timer);
  }, [hasActiveRun, load]);

  const planById = useMemo(
    () => new Map(plans.map((plan) => [plan.id, plan])),
    [plans],
  );

  const generatePlan = async (item: OpportunityPortfolioItem) => {
    setActionId(item.opportunity.id);
    try {
      await discoverApi.convert(workspace.id, item.opportunity.id);
      message.success("研究计划已生成");
      await load();
    } catch (error) {
      message.error(`计划生成失败：${errorMessage(error)}`);
    } finally {
      setActionId(null);
    }
  };

  const startDeepResearch = async (plan: ResearchPlan) => {
    setActionId(plan.id);
    try {
      const conversation = await chatApi.createConversation(`深度研究：${plan.title}`.slice(0, 80), workspace.id);
      await agentApi.start(workspace.id, {
        agent_type: "deep_research",
        prompt: "围绕该研究计划开展证据约束的深度研究：综合支持证据、反证、限制条件和未解决问题，使用简体中文提出可实现的候选方法、数学公式、算法步骤、实现细节、消融实验、统计检验和明确的证伪标准。",
        conversation_id: conversation.id,
        input: { research_plan_id: plan.id },
      });
      message.success("深度研究 Agent 已启动");
      await load();
    } catch (error) {
      message.error(`深度研究启动失败：${errorMessage(error)}`);
    } finally {
      setActionId(null);
    }
  };

  const refinePlan = async (plan: ResearchPlan) => {
    setActionId(`refine-${plan.id}`);
    try {
      const conversation = await chatApi.createConversation(`完善研究计划：${plan.title}`.slice(0, 80), workspace.id);
      await agentApi.start(workspace.id, {
        agent_type: "research_plan",
        prompt: "将当前研究计划完整改写为简体中文，并依据工作区证据补齐数据集、对比基线、评价指标、验证步骤、预期支持结果与明确的证伪标准。证据不足的选择必须标记为暂定方案，不得留空。",
        conversation_id: conversation.id,
        input: {
          research_plan_id: plan.id,
          opportunity_id: plan.opportunity_id,
          resource_constraints: plan.resource_constraints,
        },
      });
      message.success("计划完善 Agent 已启动；请前往 AI 助手审核并确认后回填原计划");
    } catch (error) {
      message.error(`计划完善启动失败：${errorMessage(error)}`);
    } finally {
      setActionId(null);
    }
  };

  const openRun = async (run: AgentRun) => {
    setReportLoading(true);
    try {
      setSelectedRun(await agentApi.get(workspace.id, run.id));
    } catch (error) {
      message.error(`报告加载失败：${errorMessage(error)}`);
    } finally {
      setReportLoading(false);
    }
  };

  const confirmRun = async (run: AgentRun) => {
    setActionId(run.id);
    try {
      await agentApi.confirm(workspace.id, run.id);
      message.success("深度研究报告已确认");
      setSelectedRun(null);
      await load();
    } catch (error) {
      message.error(`确认失败：${errorMessage(error)}`);
    } finally {
      setActionId(null);
    }
  };

  const cancelRun = (run: AgentRun) => {
    modal.confirm({
      title: "停止这次深度研究？",
      content: "已经生成的步骤记录会保留，但任务不会继续。",
      okText: "停止",
      okButtonProps: { danger: true },
      cancelText: "继续运行",
      onOk: async () => {
        await agentApi.cancel(workspace.id, run.id);
        message.success("任务已停止");
        await load();
      },
    });
  };

  const opportunityContent = portfolio.length ? (
    <List
      grid={{ gutter: 16, xs: 1, md: 2, xxl: 3 }}
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
                  : <Button key="plan" type="link" loading={actionId === item.opportunity.id} onClick={() => void generatePlan(item)}>生成研究计划</Button>,
              ]}
            >
              <Paragraph ellipsis={{ rows: 3 }}>{version?.problem_statement || item.opportunity.summary}</Paragraph>
              <Text type="secondary">研究问题</Text>
              <Paragraph ellipsis={{ rows: 2 }}>{version?.candidate_research_question || "尚未形成结构化研究问题"}</Paragraph>
              <Progress size="small" percent={Math.round((version?.evidence_coverage || 0) * 100)} format={(value) => `证据覆盖 ${value}%`} />
            </Card>
          </List.Item>
        );
      }}
    />
  ) : <Empty description="还没有已确认的研究机会" image={Empty.PRESENTED_IMAGE_SIMPLE} />;

  const planContent = plans.length ? (
    <List
      dataSource={plans}
      renderItem={(plan) => (
        <List.Item
          actions={[
            <Button key="detail" onClick={() => setSelectedPlan(plan)}>查看完整计划</Button>,
            <Button key="refine" icon={<RobotOutlined />} loading={actionId === `refine-${plan.id}`} onClick={() => void refinePlan(plan)}>AI 完善并中文化</Button>,
            <Button key="deep" type="primary" icon={<SearchOutlined />} loading={actionId === plan.id} onClick={() => void startDeepResearch(plan)}>启动深度研究</Button>,
          ]}
        >
          <List.Item.Meta
            avatar={<FileDoneOutlined style={{ fontSize: 22, color: "#1677ff" }} />}
            title={<Space wrap><Text strong>{plan.title}</Text><Tag color="blue">{plan.status}</Tag></Space>}
            description={(
              <Space direction="vertical" size={4}>
                <Text><Text type="secondary">研究问题：</Text>{plan.research_question}</Text>
                <Text><Text type="secondary">核心假设：</Text>{plan.hypothesis || "—"}</Text>
                <Text type="secondary">{plan.validation_steps.length} 个验证步骤</Text>
              </Space>
            )}
          />
        </List.Item>
      )}
    />
  ) : <Empty description="已确认机会生成计划后，会固定收纳在这里" image={Empty.PRESENTED_IMAGE_SIMPLE} />;

  const deepContent = (
    <Space direction="vertical" size={14} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        message="深度研究会冻结输入快照"
        description="Agent 会绑定启动时的研究计划和 Opportunity Version，综合 Discover 核验证据与工作区全文证据，形成中文报告，并给出候选方法、公式、实现步骤、消融实验和证伪标准；生成后仍需人工确认。"
      />
      {deepRuns.length ? (
        <List
          dataSource={deepRuns}
          renderItem={(run) => {
            const planId = String(run.input_payload.research_plan_id || "");
            const plan = planById.get(planId);
            const active = ["queued", "running"].includes(run.status);
            return (
              <List.Item>
                <Card
                  size="small"
                  style={{ width: "100%" }}
                  title={<Space wrap><RobotOutlined /><Text strong>{plan?.title || "深度研究"}</Text><Tag color={run.status === "succeeded" ? "green" : run.status === "failed" ? "red" : run.status === "waiting_for_user" ? "gold" : "blue"}>{stageLabels[run.current_stage] || run.current_stage}</Tag></Space>}
                  extra={run.conversation_id ? <Link to={`/workspaces/${workspace.id}/assistant/${run.conversation_id}`}>前往 AI 助手</Link> : null}
                >
                  <Progress percent={Math.round(run.progress * 100)} status={run.status === "failed" ? "exception" : run.status === "succeeded" ? "success" : "active"} />
                  {run.error && <Paragraph type="danger">{run.error}</Paragraph>}
                  <Space wrap>
                    <Button loading={reportLoading} onClick={() => void openRun(run)}>查看过程与报告</Button>
                    {run.status === "waiting_for_user" && <Button type="primary" icon={<CheckCircleOutlined />} loading={actionId === run.id} onClick={() => void confirmRun(run)}>确认报告</Button>}
                    {active && <Button danger icon={<StopOutlined />} onClick={() => cancelRun(run)}>停止</Button>}
                  </Space>
                </Card>
              </List.Item>
            );
          }}
        />
      ) : <Empty description="还没有深度研究运行；请在“研究计划”中选择计划并启动" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
    </Space>
  );

  const reportArtifact = selectedRun?.artifacts.find((item) => item.artifact_type === "deep_research_report");

  return (
    <Space direction="vertical" size={16} style={{ width: "100%", padding: "20px 8px 32px" }}>
      <Space align="start" style={{ width: "100%", justifyContent: "space-between" }} wrap>
        <div><Title level={2} style={{ margin: 0 }}>研究中心</Title><Text type="secondary">将已确认机会沉淀为结构化计划，并启动证据约束的深度研究。</Text></div>
        <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>刷新</Button>
      </Space>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
        <Card size="small"><Statistic title="已确认机会" value={portfolio.length} prefix={<BulbOutlined />} /></Card>
        <Card size="small"><Statistic title="研究计划" value={plans.length} prefix={<ExperimentOutlined />} /></Card>
        <Card size="small"><Statistic title="深度研究运行" value={deepRuns.length} prefix={<RobotOutlined />} /></Card>
      </div>
      <Card bodyStyle={{ paddingTop: 8 }}>
        {loading && !portfolio.length && !plans.length ? <div className="gm-loading"><Spin tip="正在加载研究资产" /></div> : (
          <Tabs items={[
            { key: "opportunities", label: `已确认机会 (${portfolio.length})`, children: opportunityContent },
            { key: "plans", label: `研究计划 (${plans.length})`, children: planContent },
            { key: "deep-research", label: `深度研究 (${deepRuns.length})`, children: deepContent },
          ]} />
        )}
      </Card>

      <Drawer title={selectedPlan?.title} open={Boolean(selectedPlan)} onClose={() => setSelectedPlan(null)} width="min(94vw, 760px)">
        {selectedPlan && <Descriptions bordered column={1} size="small">
          <Descriptions.Item label="研究问题">{selectedPlan.research_question}</Descriptions.Item>
          <Descriptions.Item label="核心假设">{selectedPlan.hypothesis}</Descriptions.Item>
          <Descriptions.Item label="范围与前提">{selectedPlan.scope_and_assumptions || "—"}</Descriptions.Item>
          <Descriptions.Item label="数据集">{values(selectedPlan.datasets)}</Descriptions.Item>
          <Descriptions.Item label="对比基线">{values(selectedPlan.baselines)}</Descriptions.Item>
          <Descriptions.Item label="评价指标">{values(selectedPlan.metrics)}</Descriptions.Item>
          <Descriptions.Item label="验证步骤">{values(selectedPlan.validation_steps)}</Descriptions.Item>
          <Descriptions.Item label="预期支持结果">{selectedPlan.expected_supporting_result || "—"}</Descriptions.Item>
          <Descriptions.Item label="证伪标准">{selectedPlan.falsification_criteria || "—"}</Descriptions.Item>
          <Descriptions.Item label="风险">{values(selectedPlan.risks)}</Descriptions.Item>
          <Descriptions.Item label="资源约束">{selectedPlan.resource_constraints || "—"}</Descriptions.Item>
        </Descriptions>}
      </Drawer>

      <Modal
        open={Boolean(selectedRun)}
        title={String(selectedRun?.result?.title || "深度研究运行详情")}
        width="min(94vw, 1120px)"
        centered
        wrapClassName="gm-research-report-modal"
        onCancel={() => setSelectedRun(null)}
        styles={{
          content: { height: "86vh", maxHeight: 920, display: "flex", flexDirection: "column", padding: 0, overflow: "hidden" },
          header: { flex: "0 0 auto", margin: 0, padding: "18px 56px 18px 24px", borderBottom: "1px solid #e8edf3" },
          body: { flex: "1 1 auto", minHeight: 0, padding: 0, overflow: "hidden" },
          footer: { flex: "0 0 auto", margin: 0, padding: "14px 24px", borderTop: "1px solid #e8edf3", background: "#fff" },
        }}
        footer={<Space>
          {selectedRun?.status === "waiting_for_user" && <Button type="primary" loading={actionId === selectedRun.id} onClick={() => void confirmRun(selectedRun)}>确认报告</Button>}
          <Button onClick={() => setSelectedRun(null)}>关闭</Button>
        </Space>}
      >
        {selectedRun && <div className="gm-research-report-layout">
          <div className="gm-research-report-summary">
            <Progress percent={Math.round(selectedRun.progress * 100)} status={selectedRun.status === "failed" ? "exception" : selectedRun.status === "succeeded" ? "success" : "active"} />
            <div className="gm-research-report-steps">
              <Steps size="small" responsive={false} items={selectedRun.steps.map((step) => ({ title: stageLabels[step.stage] || step.stage, description: step.summary, status: step.status === "completed" ? "finish" : step.status === "failed" ? "error" : "process" }))} />
            </div>
          </div>
          <div className="gm-research-report-scroll">
            {reportArtifact ? <div className="gm-chat-markdown gm-research-report"><ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>{normalizeMathMarkdown(reportArtifact.content)}</ReactMarkdown></div> : <div className="gm-research-report-empty"><Empty description={selectedRun.error || "报告尚未生成"} /></div>}
          </div>
        </div>}
      </Modal>
    </Space>
  );
}
