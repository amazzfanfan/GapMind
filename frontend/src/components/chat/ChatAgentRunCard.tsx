import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Alert, App, Button, Card, Collapse, Descriptions, Modal, Progress, Space, Steps, Tag, Typography } from "antd";
import { CheckCircleOutlined, CodeOutlined, DownloadOutlined, ExperimentOutlined, FileSearchOutlined, FileTextOutlined, InfoCircleOutlined, MessageOutlined, StopOutlined, WarningOutlined } from "@ant-design/icons";
import type { AgentRunDetail } from "../../api/agent";

const { Paragraph, Text } = Typography;

const stageLabel: Record<string, string> = {
  queued: "等待执行", preflight: "任务检查", workspace_retrieval: "检索工作区证据",
  plan_synthesis: "生成研究计划", evidence_gate: "证据检查", human_review: "等待人工确认",
  plan_binding: "固定计划快照", evidence_collection: "汇集核验证据", deep_synthesis: "深度综合",
  module_design: "设计蓝图", code_generation: "生成代码", static_review: "交付完整性检查",
  candidate_repair: "生成候选修复",
  rubric_check: "覆盖度自检", artifacts_ready: "产物已就绪",
  analysis: "结果分析", paper_writing: "论文写作", rebuttal: "审稿回复",
  saved: "已保存", failed: "执行失败", cancelled: "已取消",
};

type CheckSeverity = "blocking" | "advisory";
interface StaticCheck { name: string; passed: boolean; detail: string; severity?: CheckSeverity }

const BLOCKING_CHECKS = new Set(["blueprint_files_present", "syntax_valid", "entrypoint_present"]);

const checkSeverity = (check: StaticCheck): CheckSeverity =>
  check.severity ?? (BLOCKING_CHECKS.has(check.name) ? "blocking" : "advisory");

const asStaticChecks = (value: unknown): StaticCheck[] =>
  Array.isArray(value)
    ? value.filter((item): item is StaticCheck =>
        typeof item === "object" && item !== null && "passed" in item && "detail" in item)
    : [];

interface KnownGap { dimension: string; target: string; status: string; note?: unknown }

const asKnownGaps = (value: unknown): KnownGap[] =>
  Array.isArray(value)
    ? value.filter((item): item is KnownGap =>
        typeof item === "object" && item !== null
        && typeof (item as Record<string, unknown>).dimension === "string"
        && typeof (item as Record<string, unknown>).target === "string")
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

export default function ChatAgentRunCard({ run, loading, onRefresh, onConfirm, onCancel, onDownload, onDownloadArtifact, onRepairCode }: {
  run: AgentRunDetail;
  loading?: boolean;
  onRefresh: () => void;
  onConfirm: () => void;
  onCancel: () => void;
  onDownload: () => void;
  onDownloadArtifact?: (run: AgentRunDetail, artifactId: string) => void;
  onRepairCode?: (run: AgentRunDetail) => void;
}) {
  const { message } = App.useApp();
  const [preview, setPreview] = useState<{ id: string; filename: string; content: string } | null>(null);
  const isPlan = run.agent_type === "research_plan";
  const isDeep = run.agent_type === "deep_research";
  const isCode = run.agent_type === "code_generation";
  const active = ["queued", "running"].includes(run.status);
  const result = run.result ?? {};
  const independent = result.independent === true;
  const meta = AGENT_META[run.agent_type] ?? { label: "Agent", icon: <ExperimentOutlined /> };
  const codeArtifacts = run.artifacts.filter((item) => item.artifact_type === "code");
  const lifecycleArtifacts = run.artifacts.filter((item) => ["analysis", "paper_draft", "rebuttal"].includes(item.artifact_type));
  const reviewArtifacts = run.artifacts.filter((item) => item.artifact_type === "code_review");
  const blueprint = (result.blueprint ?? {}) as { modules?: unknown; files?: unknown };
  const blueprintModules = asStringList(blueprint.modules);
  const blueprintFiles = asStringList(blueprint.files);
  const staticReview = (result.static_review ?? {}) as { checks?: unknown };
  const staticChecks = asStaticChecks(staticReview.checks);
  const blockingChecks = staticChecks.filter((check) => checkSeverity(check) === "blocking");
  const advisoryChecks = staticChecks.filter((check) => checkSeverity(check) === "advisory");
  const blockingFailures = blockingChecks.filter((check) => !check.passed);
  const candidateRepair = (result.candidate_repair ?? null) as {
    attempt?: unknown;
    changed_files?: unknown;
    before?: { blocking?: { passed?: unknown; total?: unknown }; advisory?: { passed?: unknown; total?: unknown } };
    after?: { blocking?: { passed?: unknown; total?: unknown }; advisory?: { passed?: unknown; total?: unknown } };
  } | null;
  const repairFiles = asStringList(candidateRepair?.changed_files);
  const repairable = isCode && run.status === "succeeded" && !run.parent_run_id && staticChecks.some((check) => !check.passed);
  const rubric = (result.rubric ?? null) as { covered?: unknown; partial?: unknown; missing?: unknown } | null;
  const rubricCounts = rubric && typeof rubric.covered === "number" && typeof rubric.partial === "number" && typeof rubric.missing === "number"
    ? { covered: rubric.covered, partial: rubric.partial, missing: rubric.missing }
    : null;
  const knownGaps = asKnownGaps(result.known_gaps);
  const copy = async (value: string) => { await navigator.clipboard?.writeText(value); message.success("已复制"); };
  return <Card className="gm-agent-run-card" size="small" title={<Space>{meta.icon}<Text strong>{meta.label}</Text><Tag color={run.status === "succeeded" ? "green" : run.status === "failed" ? "red" : run.status === "waiting_for_user" ? "gold" : "blue"}>{stageLabel[run.current_stage] ?? run.current_stage}</Tag></Space>} extra={<Button type="link" size="small" onClick={onRefresh}>刷新</Button>}>
    <Progress percent={Math.round(run.progress * 100)} status={run.status === "failed" ? "exception" : run.status === "succeeded" ? "success" : "active"} />
    {run.steps.length > 0 && <Steps size="small" responsive={false} items={run.steps.map((step) => ({ title: stageLabel[step.stage] ?? step.stage, description: step.summary, status: step.status === "completed" ? "finish" : step.status === "failed" ? "error" : "process" }))} />}
    {run.error && <Paragraph type="danger">{run.error}</Paragraph>}
    {independent && <Alert type="info" showIcon style={{ marginBottom: 8 }} message="独立模式产物" description="本次仅使用你提供的材料，未检索课题空间论文或知识库。" />}
    {isPlan && Boolean(result.research_question) && <Descriptions size="small" column={1} bordered className="gm-agent-result"><Descriptions.Item label="研究问题">{String(result.research_question)}</Descriptions.Item><Descriptions.Item label="核心假设">{String(result.hypothesis ?? "")}</Descriptions.Item><Descriptions.Item label="验证步骤">{Array.isArray(result.validation_steps) ? result.validation_steps.join("；") : "—"}</Descriptions.Item><Descriptions.Item label="证伪条件">{String(result.falsification_criteria ?? "—")}</Descriptions.Item></Descriptions>}
    {run.agent_type === "analyze" && Boolean(result.verdict) && <Descriptions size="small" column={1} bordered className="gm-agent-result"><Descriptions.Item label="分析结论"><Text strong>{String(result.verdict)}</Text></Descriptions.Item><Descriptions.Item label="分析">{String(result.conclusion ?? "")}</Descriptions.Item></Descriptions>}
    {isCode && blueprintFiles.length > 0 && <Collapse size="small" items={[{ key: "blueprint", label: `项目蓝图：${blueprintModules.length} 个模块 / ${blueprintFiles.length} 个文件`, children: <Space direction="vertical" size={4}>{blueprintModules.length > 0 && <Space wrap size={4}>{blueprintModules.map((name) => <Tag key={name}>{name}</Tag>)}</Space>}<Text type="secondary">{blueprintFiles.join(" · ")}</Text></Space> }]} />}
    {isCode && staticChecks.length > 0 && <Collapse size="small" defaultActiveKey={["review"]} items={[{ key: "review", label: `交付完整性检查：阻断项 ${blockingChecks.filter((check) => check.passed).length}/${blockingChecks.length}，改进项 ${advisoryChecks.filter((check) => check.passed).length}/${advisoryChecks.length}`, children: <Space direction="vertical" size={8} style={{ width: "100%" }}>
      <Alert type={blockingFailures.length > 0 ? "warning" : "success"} showIcon message={blockingFailures.length > 0 ? `存在 ${blockingFailures.length} 项阻断问题` : "阻断项检查通过"} description="这里只做文件、语法和依赖声明等静态检查，不代表代码已经运行验证。" />
      {([["阻断项", blockingChecks], ["改进项", advisoryChecks]] as Array<[string, StaticCheck[]]>).map(([title, checks]) => checks.length > 0 && <Space key={title} direction="vertical" size={2} style={{ width: "100%" }}>
        <Text strong style={{ fontSize: 12 }}>{title}</Text>
        {checks.map((check) => <Space key={check.name} size={6}>{check.passed ? <CheckCircleOutlined style={{ color: "#52c41a" }} /> : <WarningOutlined style={{ color: "#faad14" }} />}<Tag color={check.passed ? "green" : "gold"}>{check.passed ? "通过" : "待处理"}</Tag><Text style={{ fontSize: 12 }}>{check.detail}</Text></Space>)}
      </Space>)}
      </Space> }]} />}
    {isCode && candidateRepair && <Alert type="info" showIcon style={{ marginTop: 8 }} message={`一次性候选修复（第 ${String(candidateRepair.attempt ?? 1)} 次，仅预览）`} description={<Space direction="vertical" size={2}><Text style={{ fontSize: 12 }}>修复前阻断项：{String(candidateRepair.before?.blocking?.passed ?? "?")}/{String(candidateRepair.before?.blocking?.total ?? "?")}；改进项：{String(candidateRepair.before?.advisory?.passed ?? "?")}/{String(candidateRepair.before?.advisory?.total ?? "?")}。</Text><Text style={{ fontSize: 12 }}>候选后检查结果：阻断项 ${String(candidateRepair.after?.blocking?.passed ?? "?")}/${String(candidateRepair.after?.blocking?.total ?? "?")}；改进项 ${String(candidateRepair.after?.advisory?.passed ?? "?")}/${String(candidateRepair.after?.advisory?.total ?? "?")}；变更文件：{repairFiles.join("、") || "见候选产物"}。</Text><Text type="secondary" style={{ fontSize: 12 }}>原代码未覆盖，候选未运行代码或测试。请查看 code_repair_diff.md 后人工审查。</Text></Space>} />}
    {isCode && rubricCounts && <Space wrap size={6} style={{ marginTop: 4 }}>
      <Text type="secondary" style={{ fontSize: 12 }}>计划覆盖度：</Text>
      <Tag color="green">覆盖 {rubricCounts.covered}</Tag>
      <Tag color="gold">部分 {rubricCounts.partial}</Tag>
      <Tag color="red">未覆盖 {rubricCounts.missing}</Tag>
    </Space>}
    {isCode && rubricCounts && <Alert type="info" showIcon style={{ marginTop: 8 }} message="计划覆盖度自检，不代表代码已运行验证" description="该报告只对照研究计划检查数据集、基线、指标和验证步骤；生成代码仍需人工审查。" />}
    {isCode && knownGaps.length > 0 && <Alert type="warning" showIcon icon={<WarningOutlined />} style={{ marginTop: 8 }} message={`已知缺口 ${knownGaps.length} 项`} description={<Space direction="vertical" size={2}>{knownGaps.map((gap) => <Text key={`${gap.dimension}:${gap.target}`} style={{ fontSize: 12 }}><Tag>{gap.dimension}</Tag>{gap.target}{typeof gap.note === "string" && gap.note ? `：${gap.note}` : `（${gap.status === "partial" ? "部分覆盖" : "未覆盖"}）`}</Text>)}<Text type="secondary" style={{ fontSize: 12 }}>可到研究计划页调整范围后重新生成代码。</Text></Space>} />}
    {isCode && codeArtifacts.length > 0 && <Alert type="info" showIcon icon={<InfoCircleOutlined />} style={{ marginTop: 8 }} message="AI 生成的实验骨架" description="代码由 AI 自动生成，可能存在未实现或不完整之处，仅供预览与人工审查；使用前请查看“计划覆盖度自检”与已知缺口。" />}
    {codeArtifacts.length > 0 && <Collapse size="small" items={[{ key: "files", label: `${codeArtifacts.length} 个代码文件`, children: <Space wrap>{codeArtifacts.map((artifact) => <Space key={artifact.id} size={4}>{<Button size="small" onClick={() => setPreview({ id: artifact.id, filename: artifact.filename, content: artifact.content })}>{artifact.filename}</Button>}{asStringList(artifact.metadata.evidence_refs).map((ref) => <Tag key={ref} color="blue" style={{ marginInlineEnd: 0 }}>{ref}</Tag>)}</Space>)}</Space> }]} />}
    {reviewArtifacts.length > 0 && <Collapse size="small" items={[{ key: "rubric", label: candidateRepair ? "候选修复报告与变更预览" : "计划覆盖度自检报告", children: <Space wrap>{reviewArtifacts.map((artifact) => <Space key={artifact.id} size={4}><Button size="small" onClick={() => setPreview({ id: artifact.id, filename: artifact.filename, content: artifact.content })}>{artifact.filename}</Button>{onDownloadArtifact && <Button size="small" type="text" icon={<DownloadOutlined />} onClick={() => onDownloadArtifact(run, artifact.id)} aria-label={`下载 ${artifact.filename}`} />}</Space>)}</Space> }]} />}
    {lifecycleArtifacts.length > 0 && <Collapse size="small" items={[{ key: "docs", label: `${lifecycleArtifacts.length} 份文档产物`, children: <Space wrap>{lifecycleArtifacts.map((artifact) => <Button key={artifact.id} size="small" onClick={() => setPreview({ id: artifact.id, filename: artifact.filename, content: artifact.content })}>{artifact.filename}</Button>)}</Space> }]} />}
    <Space wrap style={{ marginTop: 12 }}>
      {run.status === "waiting_for_user" && (isPlan || isDeep) && <Button type="primary" icon={<CheckCircleOutlined />} loading={loading} onClick={onConfirm}>{isDeep ? "确认深度研究报告" : "确认并保存到研究中心"}</Button>}
      {active && <Button danger icon={<StopOutlined />} loading={loading} onClick={onCancel}>停止任务</Button>}
      {repairable && onRepairCode && <Button icon={<WarningOutlined />} loading={loading} onClick={() => onRepairCode(run)}>生成一次候选修复</Button>}
      {isCode && run.status === "succeeded" && <Button type="primary" icon={<DownloadOutlined />} onClick={onDownload}>下载 ZIP</Button>}
    </Space>
    <Modal open={Boolean(preview)} title={preview?.filename} width={900} footer={<Space>{onDownloadArtifact && preview?.id && <Button icon={<DownloadOutlined />} onClick={() => onDownloadArtifact(run, preview.id)}>下载此文件</Button>}<Button onClick={() => void copy(preview?.content ?? "")}>复制</Button><Button type="primary" onClick={() => setPreview(null)}>关闭</Button></Space>} onCancel={() => setPreview(null)}>{preview?.filename.endsWith(".md") ? <div className="gm-chat-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{preview.content}</ReactMarkdown></div> : <pre className="gm-agent-code-preview"><code>{preview?.content}</code></pre>}</Modal>
  </Card>;
}
