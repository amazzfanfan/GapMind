import { useState } from "react";
import { App, Button, Card, Collapse, Descriptions, Modal, Progress, Space, Steps, Tag, Typography } from "antd";
import { CheckCircleOutlined, CodeOutlined, DownloadOutlined, ExperimentOutlined, SafetyCertificateOutlined, SearchOutlined, StopOutlined } from "@ant-design/icons";
import type { AgentRunDetail } from "../../api/agent";

const { Paragraph, Text } = Typography;

const stageLabel: Record<string, string> = {
  queued: "等待执行", preflight: "任务检查", workspace_retrieval: "检索工作区证据",
  plan_synthesis: "生成研究计划", evidence_gate: "证据检查", human_review: "等待人工确认",
  plan_binding: "固定计划快照", evidence_collection: "汇集核验证据", deep_synthesis: "深度综合",
  code_generation: "生成代码", static_review: "产物检查", artifacts_ready: "产物已就绪",
  saved: "已保存", failed: "执行失败", cancelled: "已取消",
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
  const codeArtifacts = run.artifacts.filter((item) => item.artifact_type === "code");
  const copy = async (value: string) => { await navigator.clipboard?.writeText(value); message.success("已复制"); };
  const icon = isPlan ? <ExperimentOutlined /> : isDeep ? <SearchOutlined /> : <CodeOutlined />;
  const title = isPlan ? "研究计划 Agent" : isDeep ? "深度研究 Agent" : "代码生成 Agent";
  return <Card className="gm-agent-run-card" size="small" title={<Space>{icon}<Text strong>{title}</Text><Tag color={run.status === "succeeded" ? "green" : run.status === "failed" ? "red" : run.status === "waiting_for_user" ? "gold" : "blue"}>{stageLabel[run.current_stage] ?? run.current_stage}</Tag></Space>} extra={<Button type="link" size="small" onClick={onRefresh}>刷新</Button>}>
    <Progress percent={Math.round(run.progress * 100)} status={run.status === "failed" ? "exception" : run.status === "succeeded" ? "success" : "active"} />
    {run.steps.length > 0 && <Steps size="small" responsive={false} items={run.steps.map((step) => ({ title: stageLabel[step.stage] ?? step.stage, description: step.summary, status: step.status === "completed" ? "finish" : step.status === "failed" ? "error" : "process" }))} />}
    {run.error && <Paragraph type="danger">{run.error}</Paragraph>}
    {isPlan && Boolean(result.research_question) && <Descriptions size="small" column={1} bordered className="gm-agent-result"><Descriptions.Item label="研究问题">{String(result.research_question)}</Descriptions.Item><Descriptions.Item label="核心假设">{String(result.hypothesis ?? "")}</Descriptions.Item><Descriptions.Item label="验证步骤">{Array.isArray(result.validation_steps) ? result.validation_steps.join("；") : "—"}</Descriptions.Item><Descriptions.Item label="证伪条件">{String(result.falsification_criteria ?? "—")}</Descriptions.Item></Descriptions>}
    {isDeep && Boolean(result.executive_summary) && <Descriptions size="small" column={1} bordered className="gm-agent-result"><Descriptions.Item label="报告标题">{String(result.title ?? "深度研究报告")}</Descriptions.Item><Descriptions.Item label="核心结论">{String(result.executive_summary)}</Descriptions.Item><Descriptions.Item label="精炼假设">{String(result.refined_hypothesis ?? "")}</Descriptions.Item><Descriptions.Item label="引用证据">{Array.isArray(result.evidence_refs) ? result.evidence_refs.join("、") : "—"}</Descriptions.Item></Descriptions>}
    {codeArtifacts.length > 0 && <Collapse size="small" items={[{ key: "files", label: `${codeArtifacts.length} 个代码文件`, children: <Space wrap>{codeArtifacts.map((artifact) => <Button key={artifact.id} size="small" onClick={() => setPreview({ filename: artifact.filename, content: artifact.content })}>{artifact.filename}</Button>)}</Space> }]} />}
    <Space wrap style={{ marginTop: 12 }}>
      {run.status === "waiting_for_user" && (isPlan || isDeep) && <Button type="primary" icon={<CheckCircleOutlined />} loading={loading} onClick={onConfirm}>{isDeep ? "确认深度研究报告" : "确认并保存到研究中心"}</Button>}
      {active && <Button danger icon={<StopOutlined />} loading={loading} onClick={onCancel}>停止任务</Button>}
      {isCode && run.status === "succeeded" && <><Button type="primary" icon={<DownloadOutlined />} onClick={onDownload}>下载 ZIP</Button><Button icon={<SafetyCertificateOutlined />} onClick={onValidate}>隔离验证</Button></>}
    </Space>
    <Modal open={Boolean(preview)} title={preview?.filename} width={900} footer={<Space><Button onClick={() => void copy(preview?.content ?? "")}>复制</Button><Button type="primary" onClick={() => setPreview(null)}>关闭</Button></Space>} onCancel={() => setPreview(null)}><pre className="gm-agent-code-preview"><code>{preview?.content}</code></pre></Modal>
  </Card>;
}
