import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { App, Button, Card, Collapse, Descriptions, Modal, Progress, Space, Steps, Tag, Typography } from "antd";
import { CheckCircleOutlined, CodeOutlined, DownloadOutlined, ExperimentOutlined, FileSearchOutlined, FileTextOutlined, MessageOutlined, SafetyCertificateOutlined, StopOutlined, WarningOutlined } from "@ant-design/icons";
import type { AgentRunDetail } from "../../api/agent";

const { Paragraph, Text } = Typography;

const stageLabel: Record<string, string> = {
  queued: "等待执行", preflight: "任务检查", workspace_retrieval: "检索工作区证据",
  plan_synthesis: "生成研究计划", evidence_gate: "证据检查", human_review: "等待人工确认",
  plan_binding: "固定计划快照", evidence_collection: "汇集核验证据", deep_synthesis: "深度综合",
  module_design: "设计蓝图", code_generation: "生成代码", static_review: "静态检查",
  rubric_check: "覆盖度自检", artifacts_ready: "产物已就绪",
  analysis: "结果分析", paper_writing: "论文写作", rebuttal: "审稿回复",
  saved: "已保存", failed: "执行失败", cancelled: "已取消",
};

interface StaticCheck { name: string; passed: boolean; detail: string }

const asStaticChecks = (value: unknown): StaticCheck[] =>
  Array.isArray(value)
    ? value.filter((item): item is StaticCheck =>
        typeof item === "object" && item !== null && "passed" in item && "detail" in item)
    : [];

const asStringList = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];

const AGENT_META: Record<string, { label: string; icon: React.ReactNode }> = {
  research_plan: { label: "研究计划 Agent", icon: <ExperimentOutlined /> },
  code_generation: { label: "代码生成 Agent", icon: <CodeOutlined /> },
  analyze: { label: "结果分析 Agent", icon: <FileSearchOutlined /> },
  write: { label: "论文写作 Agent", icon: <FileTextOutlined /> },
  respond: { label: "审稿回复 Agent", icon: <MessageOutlined /> },
};

export default function ChatAgentRunCard({ run, loading, onRefresh, onConfirm, onCancel, onValidate, onDownload }: {
  run: AgentRunDetail;
  loading?: boolean;
  onRefresh: () => void;
  onConfirm: () => void;
  onCancel: () => void;
  onValidate: () => void;
  onDownload: () => void;
}) {
  const { message } = App.useApp();
  const [preview, setPreview] = useState<{ filename: string; content: string } | null>(null);
  const isPlan = run.agent_type === "research_plan";
  const isDeep = run.agent_type === "deep_research";
  const isCode = run.agent_type === "code_generation";
  const active = ["queued", "running"].includes(run.status);
  const result = run.result ?? {};
  const meta = AGENT_META[run.agent_type] ?? { label: "Agent", icon: <ExperimentOutlined /> };
  const codeArtifacts = run.artifacts.filter((item) => item.artifact_type === "code");
  const lifecycleArtifacts = run.artifacts.filter((item) => ["analysis", "paper_draft", "rebuttal"].includes(item.artifact_type));
  const reviewArtifacts = run.artifacts.filter((item) => item.artifact_type === "code_review");
  const blueprint = (result.blueprint ?? {}) as { modules?: unknown; files?: unknown };
  const blueprintModules = asStringList(blueprint.modules);
  const blueprintFiles = asStringList(blueprint.files);
  const staticReview = (result.static_review ?? {}) as { checks?: unknown };
  const staticChecks = asStaticChecks(staticReview.checks);
  const rubric = (result.rubric ?? null) as { covered?: unknown; partial?: unknown; missing?: unknown } | null;
  const rubricCounts = rubric && typeof rubric.covered === "number" && typeof rubric.partial === "number" && typeof rubric.missing === "number"
    ? { covered: rubric.covered, partial: rubric.partial, missing: rubric.missing }
    : null;
  const copy = async (value: string) => { await navigator.clipboard?.writeText(value); message.success("已复制"); };
  return <Card className="gm-agent-run-card" size="small" title={<Space>{meta.icon}<Text strong>{meta.label}</Text><Tag color={run.status === "succeeded" ? "green" : run.status === "failed" ? "red" : run.status === "waiting_for_user" ? "gold" : "blue"}>{stageLabel[run.current_stage] ?? run.current_stage}</Tag></Space>} extra={<Button type="link" size="small" onClick={onRefresh}>刷新</Button>}>
    <Progress percent={Math.round(run.progress * 100)} status={run.status === "failed" ? "exception" : run.status === "succeeded" ? "success" : "active"} />
    {run.steps.length > 0 && <Steps size="small" responsive={false} items={run.steps.map((step) => ({ title: stageLabel[step.stage] ?? step.stage, description: step.summary, status: step.status === "completed" ? "finish" : step.status === "failed" ? "error" : "process" }))} />}
    {run.error && <Paragraph type="danger">{run.error}</Paragraph>}
    {isPlan && Boolean(result.research_question) && <Descriptions size="small" column={1} bordered className="gm-agent-result"><Descriptions.Item label="研究问题">{String(result.research_question)}</Descriptions.Item><Descriptions.Item label="核心假设">{String(result.hypothesis ?? "")}</Descriptions.Item><Descriptions.Item label="验证步骤">{Array.isArray(result.validation_steps) ? result.validation_steps.join("；") : "—"}</Descriptions.Item><Descriptions.Item label="证伪条件">{String(result.falsification_criteria ?? "—")}</Descriptions.Item></Descriptions>}
    {run.agent_type === "analyze" && Boolean(result.verdict) && <Descriptions size="small" column={1} bordered className="gm-agent-result"><Descriptions.Item label="分析结论"><Text strong>{String(result.verdict)}</Text></Descriptions.Item><Descriptions.Item label="分析">{String(result.conclusion ?? "")}</Descriptions.Item></Descriptions>}
    {isCode && blueprintFiles.length > 0 && <Collapse size="small" items={[{ key: "blueprint", label: `项目蓝图：${blueprintModules.length} 个模块 / ${blueprintFiles.length} 个文件`, children: <Space direction="vertical" size={4}>{blueprintModules.length > 0 && <Space wrap size={4}>{blueprintModules.map((name) => <Tag key={name}>{name}</Tag>)}</Space>}<Text type="secondary">{blueprintFiles.join(" · ")}</Text></Space> }]} />}
    {isCode && staticChecks.length > 0 && <Collapse size="small" defaultActiveKey={["review"]} items={[{ key: "review", label: `静态检查：${staticChecks.filter((check) => check.passed).length}/${staticChecks.length} 项通过`, children: <Space direction="vertical" size={2}>{staticChecks.map((check) => <Space key={check.name} size={6}>{check.passed ? <CheckCircleOutlined style={{ color: "#52c41a" }} /> : <WarningOutlined style={{ color: "#faad14" }} />}<Text style={{ fontSize: 12 }}>{check.detail}</Text></Space>)}</Space> }]} />}
    {isCode && rubricCounts && <Space wrap size={6} style={{ marginTop: 4 }}>
      <Text type="secondary" style={{ fontSize: 12 }}>计划覆盖度：</Text>
      <Tag color="green">覆盖 {rubricCounts.covered}</Tag>
      <Tag color="gold">部分 {rubricCounts.partial}</Tag>
      <Tag color="red">未覆盖 {rubricCounts.missing}</Tag>
    </Space>}
    {codeArtifacts.length > 0 && <Collapse size="small" items={[{ key: "files", label: `${codeArtifacts.length} 个代码文件`, children: <Space wrap>{codeArtifacts.map((artifact) => <Space key={artifact.id} size={4}>{<Button size="small" onClick={() => setPreview({ filename: artifact.filename, content: artifact.content })}>{artifact.filename}</Button>}{asStringList(artifact.metadata.evidence_refs).map((ref) => <Tag key={ref} color="blue" style={{ marginInlineEnd: 0 }}>{ref}</Tag>)}</Space>)}</Space> }]} />}
    {reviewArtifacts.length > 0 && <Collapse size="small" items={[{ key: "rubric", label: "计划覆盖度自检报告", children: <Space wrap>{reviewArtifacts.map((artifact) => <Button key={artifact.id} size="small" onClick={() => setPreview({ filename: artifact.filename, content: artifact.content })}>{artifact.filename}</Button>)}</Space> }]} />}
    {lifecycleArtifacts.length > 0 && <Collapse size="small" items={[{ key: "docs", label: `${lifecycleArtifacts.length} 份文档产物`, children: <Space wrap>{lifecycleArtifacts.map((artifact) => <Button key={artifact.id} size="small" onClick={() => setPreview({ filename: artifact.filename, content: artifact.content })}>{artifact.filename}</Button>)}</Space> }]} />}
    <Space wrap style={{ marginTop: 12 }}>
      {run.status === "waiting_for_user" && (isPlan || isDeep) && <Button type="primary" icon={<CheckCircleOutlined />} loading={loading} onClick={onConfirm}>{isDeep ? "确认深度研究报告" : "确认并保存到研究中心"}</Button>}
      {active && <Button danger icon={<StopOutlined />} loading={loading} onClick={onCancel}>停止任务</Button>}
      {isCode && run.status === "succeeded" && <><Button type="primary" icon={<DownloadOutlined />} onClick={onDownload}>下载 ZIP</Button><Button icon={<SafetyCertificateOutlined />} onClick={onValidate}>隔离验证</Button></>}
    </Space>
    <Modal open={Boolean(preview)} title={preview?.filename} width={900} footer={<Space><Button onClick={() => void copy(preview?.content ?? "")}>复制</Button><Button type="primary" onClick={() => setPreview(null)}>关闭</Button></Space>} onCancel={() => setPreview(null)}>{preview?.filename.endsWith(".md") ? <div className="gm-chat-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{preview.content}</ReactMarkdown></div> : <pre className="gm-agent-code-preview"><code>{preview?.content}</code></pre>}</Modal>
  </Card>;
}
