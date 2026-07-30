import { useCallback, useEffect, useMemo, useState } from "react";
import {
  App,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Divider,
  Drawer,
  Empty,
  Form,
  Grid,
  Input,
  List,
  Modal,
  Progress,
  Select,
  Space,
  Steps,
  Tag,
  Typography,
} from "antd";
import { BulbOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { useParams } from "react-router-dom";
import { discoverApi, type DiscoverExternalCandidate, type DiscoverRun, type OpportunityDetail, type ResearchOpportunity } from "../api/discover";

const { Text, Title, Paragraph } = Typography;

function errorMessage(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: { message?: string } } } }).response?.data?.detail;
  return detail?.message || (error as Error).message || "Request failed";
}

function statusColor(status: string): string {
  if (["succeeded", "confirmed", "edited_confirmed", "verified"].includes(status)) return "green";
  if (["failed", "cancelled", "rejected"].includes(status)) return "red";
  if (["waiting_for_user", "needs_more_evidence", "verification_incomplete", "deferred"].includes(status)) return "orange";
  return "blue";
}

function verificationStatusLabel(status: string): string {
  switch (status) {
    case "selected": return "Selected · starting verification";
    case "imported_pending_parse": return "PDF downloaded · parsing";
    case "verified": return "Full text verified";
    case "no_pdf": return "No PDF available";
    case "import_failed": return "PDF download failed";
    default: return "Not selected";
  }
}

function verificationStatusColor(status: string): string {
  if (status === "verified") return "green";
  if (status === "no_pdf" || status === "import_failed") return "red";
  if (status === "selected" || status === "imported_pending_parse") return "processing";
  return "default";
}

function verificationActionLabel(status: string): string {
  if (status === "selected") return "Starting...";
  if (status === "imported_pending_parse") return "Parsing PDF...";
  if (status === "verified") return "Verified";
  if (status === "no_pdf") return "Retry PDF download";
  if (status === "import_failed") return "Retry download";
  return "Import and verify";
}

function verificationActionDisabled(status: string): boolean {
  return ["selected", "imported_pending_parse", "verified"].includes(status);
}

const STAGES = ["preflight", "workspace_retrieval", "counter_evidence", "external_search", "synthesis", "saved"];

export default function DiscoverPage() {
  const { id: workspaceId } = useParams<{ id: string }>();
  const { message } = App.useApp();
  const screens = Grid.useBreakpoint();
  const [form] = Form.useForm();
  const [runs, setRuns] = useState<DiscoverRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<Awaited<ReturnType<typeof discoverApi.getRun>> | null>(null);
  const [opportunities, setOpportunities] = useState<ResearchOpportunity[]>([]);
  const [selectedOpportunity, setSelectedOpportunity] = useState<OpportunityDetail | null>(null);
  const [runModalOpen, setRunModalOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const selectedRun = useMemo(() => runs.find((run) => run.id === selectedRunId) ?? null, [runs, selectedRunId]);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    setLoading(true);
    try {
      const [runResponse, opportunityResponse] = await Promise.all([
        discoverApi.listRuns(workspaceId),
        discoverApi.listOpportunities(workspaceId),
      ]);
      setRuns(runResponse.items);
      setOpportunities(opportunityResponse.items);
      const current = selectedRunId ? runResponse.items.find((item) => item.id === selectedRunId) : runResponse.items[0];
      if (current && !selectedRunId) setSelectedRunId(current.id);
    } catch (error) {
      message.error(`Failed to load Discover: ${errorMessage(error)}`);
    } finally {
      setLoading(false);
    }
  }, [message, selectedRunId, workspaceId]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!workspaceId || !selectedRun) return;
    let active = true;
    const refresh = async () => {
      try {
        const detail = await discoverApi.getRun(workspaceId, selectedRun.id);
        if (active) setRunDetail(detail);
      } catch { /* the main page already reports initial load failures */ }
    };
    void refresh();
    if (!["queued", "running"].includes(selectedRun.status)) return () => { active = false; };
    const timer = window.setInterval(() => { void refresh(); }, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [selectedRun, workspaceId]);

  const openOpportunity = async (opportunityId: string) => {
    if (!workspaceId) return;
    try { setSelectedOpportunity(await discoverApi.getOpportunity(workspaceId, opportunityId)); }
    catch (error) { message.error(`Failed to load opportunity: ${errorMessage(error)}`); }
  };

  const submitRun = async (values: Record<string, unknown>) => {
    if (!workspaceId) return;
    setSubmitting(true);
    try {
      const response = await discoverApi.createRun(workspaceId, {
        input: {
          topic: String(values.topic || "").trim() || undefined,
          constraints: String(values.constraints || "").trim() || undefined,
          keywords: String(values.keywords || "").split(/[,\n]/).map((value) => value.trim()).filter(Boolean),
        },
        scope: { year_from: values.year_from as number | undefined, year_to: values.year_to as number | undefined, open_access_preferred: Boolean(values.open_access_preferred) },
        config: { max_opportunities: Number(values.max_opportunities || 3), top_k: 10, include_counter_evidence: true },
      });
      message.success(`Discover run started (${response.run_id.slice(0, 8)})`);
      setRunModalOpen(false);
      form.resetFields();
      await load();
    } catch (error) { message.error(`Could not start Discover: ${errorMessage(error)}`); }
    finally { setSubmitting(false); }
  };

  const actOnOpportunity = async (action: "confirm" | "reject" | "defer" | "convert") => {
    if (!workspaceId || !selectedOpportunity) return;
    const item = selectedOpportunity.opportunity;
    setActionLoading(true);
    try {
      if (action === "confirm") await discoverApi.confirm(workspaceId, item.id, selectedOpportunity.current_version?.id);
      if (action === "reject") await discoverApi.reject(workspaceId, item.id, "Rejected from Discover Workbench");
      if (action === "defer") await discoverApi.defer(workspaceId, item.id, "Deferred for later review", "Revisit after more full-text evidence is imported");
      if (action === "convert") { await discoverApi.convert(workspaceId, item.id); message.success("Research plan created"); }
      if (action !== "convert") message.success(`Opportunity ${action}ed`);
      await openOpportunity(item.id); await load();
    } catch (error) { message.error(`Action failed: ${errorMessage(error)}`); }
    finally { setActionLoading(false); }
  };

  const selectExternal = async (candidate: DiscoverExternalCandidate) => {
    if (!workspaceId || !runDetail) return;
    try {
      await discoverApi.selectExternal(workspaceId, runDetail.id, [candidate.id]);
      message.success("Paper selected; PDF download and verification started");
      await load();
    }
    catch (error) { message.error(`Selection failed: ${errorMessage(error)}`); }
  };

  const activeStage = useMemo(() => Math.max(0, STAGES.indexOf(runDetail?.stage || selectedRun?.stage || "preflight")), [runDetail?.stage, selectedRun?.stage]);

  if (!workspaceId) return <Empty description="Workspace not found" />;

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" size={20} style={{ width: "100%" }}>
        <Space style={{ width: "100%", justifyContent: "space-between" }}>
          <div><Title level={2} style={{ margin: 0 }}>Discover Workbench</Title><Text type="secondary">Evidence-grounded research opportunity discovery</Text></div>
          <Space><Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>Refresh</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => setRunModalOpen(true)}>New Discover Run</Button></Space>
        </Space>
        <div style={{ display: "grid", gridTemplateColumns: screens.md ? "minmax(230px, 0.28fr) minmax(0, 0.72fr)" : "minmax(0, 1fr)", gap: 20 }}>
          <Card title={`Run history (${runs.length})`} bodyStyle={{ padding: 0 }}>
            <List
              dataSource={runs}
              locale={{ emptyText: "No Discover runs yet" }}
              renderItem={(run) => <List.Item onClick={() => setSelectedRunId(run.id)} style={{ cursor: "pointer", padding: "14px 16px", background: selectedRun?.id === run.id ? "#f0f5ff" : undefined }}>
                <List.Item.Meta avatar={<BulbOutlined />} title={<Text ellipsis>{run.input_topic || "Claim-driven discovery"}</Text>} description={<Space wrap><Tag color={statusColor(run.status)}>{run.status}</Tag><Text type="secondary">{Math.round(run.progress * 100)}%</Text></Space>} />
              </List.Item>}
            />
          </Card>
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            <Card title="Run overview" extra={selectedRun && <Tag color={statusColor(selectedRun.status)}>{selectedRun.status}</Tag>}>
              {!selectedRun ? <Empty description="Start a run to inspect its progress and candidates" /> : <>
                <Descriptions size="small" column={{ xs: 1, sm: 2 }}><Descriptions.Item label="Topic">{selectedRun.input_topic || "Claim-driven"}</Descriptions.Item><Descriptions.Item label="Verification">{selectedRun.verification_status}</Descriptions.Item><Descriptions.Item label="Stage">{selectedRun.stage}</Descriptions.Item><Descriptions.Item label="Created">{new Date(selectedRun.created_at).toLocaleString()}</Descriptions.Item></Descriptions>
                <Progress percent={Math.round((runDetail?.progress ?? selectedRun.progress) * 100)} status={selectedRun.status === "failed" ? "exception" : undefined} />
                <Steps size="small" current={activeStage} items={STAGES.map((stage) => ({ title: stage.replaceAll("_", " ") }))} />
                {selectedRun.error_message && <Paragraph type="danger" style={{ marginTop: 16 }}>{selectedRun.error_message}</Paragraph>}
              </>}
            </Card>
            <Card title={`Opportunity candidates (${opportunities.length})`}>
              {opportunities.length === 0 ? <Empty description="Candidates will appear after synthesis" /> : <List dataSource={opportunities.filter((item) => !selectedRun || item.discover_run_id === selectedRun.id)} renderItem={(item) => <List.Item actions={[<Button key="open" type="link" onClick={() => void openOpportunity(item.id)}>Open details</Button>]}>
                <List.Item.Meta title={<Space><Text strong>{item.title}</Text><Tag color={statusColor(item.status)}>{item.status}</Tag></Space>} description={<Paragraph ellipsis={{ rows: 2 }} style={{ margin: 0 }}>{item.summary}</Paragraph>} />
                <Tag>{Math.round(item.confidence * 100)}% confidence</Tag>
              </List.Item>} />}
            </Card>
            {runDetail?.external_candidates?.length ? <Card title="External candidates for verification"><List size="small" dataSource={runDetail.external_candidates} renderItem={(candidate) => <List.Item actions={[<Button key="select" size="small" onClick={() => void selectExternal(candidate)} disabled={verificationActionDisabled(candidate.verification_status)}>{verificationActionLabel(candidate.verification_status)}</Button>]}><List.Item.Meta title={`${candidate.rank}. ${candidate.title}`} description={<Space wrap><Tag>{candidate.year || "Year unknown"}</Tag><Tag>{candidate.evidence_level}</Tag><Tag color={verificationStatusColor(candidate.verification_status)}>{verificationStatusLabel(candidate.verification_status)}</Tag><Tag>{candidate.role}</Tag></Space>} /></List.Item>} /></Card> : null}
          </Space>
        </div>
      </Space>

      <Modal title="Run Discover" open={runModalOpen} onCancel={() => setRunModalOpen(false)} onOk={() => void form.submit()} okText="Run Discover" confirmLoading={submitting} width={640}>
        <Form form={form} layout="vertical" onFinish={(values) => void submitRun(values)} initialValues={{ max_opportunities: 3 }}>
          <Form.Item name="topic" label="Research topic or question" rules={[{ required: true, message: "Enter a topic or question" }]}><Input.TextArea rows={4} placeholder="e.g. Robust self-interpretable GNNs under distribution shift" /></Form.Item>
          <Form.Item name="keywords" label="Keywords"><Input placeholder="Separate keywords with commas" /></Form.Item>
          <Space style={{ width: "100%" }}><Form.Item name="year_from" label="From"><Input type="number" placeholder="2020" /></Form.Item><Form.Item name="year_to" label="To"><Input type="number" placeholder="2026" /></Form.Item><Form.Item name="max_opportunities" label="Max candidates"><Select options={[1, 2, 3, 5].map((value) => ({ value, label: String(value) }))} /></Form.Item></Space>
          <Form.Item name="constraints" label="Constraints"><Input.TextArea rows={3} placeholder="Datasets, compute, time, or domain constraints" /></Form.Item>
          <Form.Item name="open_access_preferred" valuePropName="checked"><Checkbox>Prefer open-access papers for verification</Checkbox></Form.Item>
          <Text type="secondary">The run is asynchronous. External metadata is saved as a snapshot; full-text verification is never silently treated as complete.</Text>
        </Form>
      </Modal>

      <Drawer title={selectedOpportunity?.opportunity.title} open={selectedOpportunity !== null} width={720} onClose={() => setSelectedOpportunity(null)}>
        {selectedOpportunity && <OpportunityPanel detail={selectedOpportunity} loading={actionLoading} onAction={(action) => void actOnOpportunity(action)} />}
      </Drawer>
    </div>
  );
}

function OpportunityPanel({ detail, loading, onAction }: { detail: OpportunityDetail; loading: boolean; onAction: (action: "confirm" | "reject" | "defer" | "convert") => void }) {
  const version = detail.current_version;
  return <Space direction="vertical" style={{ width: "100%" }}>
    <Space wrap><Tag color={statusColor(detail.opportunity.status)}>{detail.opportunity.status}</Tag><Tag>{version?.verification_status || "unverified"}</Tag><Tag>Evidence {Math.round((version?.evidence_coverage || 0) * 100)}%</Tag><Tag>Confidence {Math.round(detail.opportunity.confidence * 100)}%</Tag></Space>
    <Divider orientation="left">Overview</Divider>
    <Paragraph>{version?.problem_statement || detail.opportunity.summary}</Paragraph>
    <Descriptions column={1} size="small"><Descriptions.Item label="Scope">{version?.research_scope || "—"}</Descriptions.Item><Descriptions.Item label="Why existing work is insufficient">{version?.why_existing_work_is_insufficient || detail.opportunity.rationale}</Descriptions.Item><Descriptions.Item label="Research question">{version?.candidate_research_question || "—"}</Descriptions.Item><Descriptions.Item label="Hypothesis">{version?.candidate_hypothesis || "—"}</Descriptions.Item></Descriptions>
    <Divider orientation="left">Evidence ({detail.evidence.length})</Divider>
    <List size="small" dataSource={detail.evidence} locale={{ emptyText: "No saved evidence" }} renderItem={(evidence) => <List.Item><Space direction="vertical" style={{ width: "100%" }}><Space wrap><Tag color={evidence.relation === "contradicts" ? "red" : "blue"}>{evidence.relation}</Tag><Tag>{evidence.source_scope}</Tag><Tag>{evidence.evidence_level}</Tag></Space><Text>{evidence.display_excerpt || "No excerpt"}</Text></Space></List.Item>} />
    <Divider orientation="left">Validation plan</Divider>
    <List size="small" dataSource={version?.candidate_validation_plan?.steps as string[] || []} renderItem={(step) => <List.Item>{step}</List.Item>} locale={{ emptyText: "No structured validation steps" }} />
    <Divider orientation="left">Human decision</Divider>
    <Space wrap><Button danger onClick={() => onAction("reject")} loading={loading}>Reject</Button><Button onClick={() => onAction("defer")} loading={loading}>Defer</Button><Button type="primary" onClick={() => onAction("confirm")} loading={loading} disabled={detail.opportunity.status === "needs_more_evidence"}>Confirm</Button>{["confirmed", "edited_confirmed"].includes(detail.opportunity.status) && <Button onClick={() => onAction("convert")} loading={loading}>Generate Research Plan</Button>}</Space>
    {detail.plan && <Card size="small" title="Research Plan created"><Paragraph>{detail.plan.research_question}</Paragraph></Card>}
  </Space>;
}
