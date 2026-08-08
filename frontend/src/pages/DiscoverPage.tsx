import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
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
  Popconfirm,
  Progress,
  Select,
  Space,
  Steps,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { BulbOutlined, CloseCircleOutlined, DeleteOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { useParams, useSearchParams } from "react-router-dom";
import { discoverApi, type DiscoverExternalCandidate, type DiscoverRun, type OpportunityDetail, type ResearchOpportunity } from "../api/discover";
import { OpportunityEvidenceViewer } from "../components/EvidenceViewer";
import { currentRunStage, currentRunStatus, DISCOVER_STAGES, pollingInterval, selectedOpportunityCount, stageIndex, TERMINAL_RUN_STATUSES } from "../state/discoverState";

const { Text, Title, Paragraph } = Typography;

function errorMessage(error: unknown): string {
  const response = error as { response?: { status?: number; data?: { detail?: { message?: string; error?: string } } } };
  const detail = response.response?.data?.detail;
  if (response.response?.status === 409) return detail?.message || "This item changed elsewhere. Refresh and try again.";
  return detail?.message || (error as Error).message || "Request failed";
}

function statusColor(status: string): string {
  if (["succeeded", "confirmed", "edited_confirmed", "verified"].includes(status)) return "green";
  if (["failed", "cancelled", "rejected", "verification_failed"].includes(status)) return "red";
  if (["waiting_for_user", "waiting_for_fulltext", "needs_more_evidence", "reviewable_with_warning", "verification_incomplete", "verified_with_warnings", "deferred"].includes(status)) return "orange";
  return "blue";
}

function agentStepColor(status: string): string {
  if (status === "completed") return "green";
  if (status === "waiting") return "orange";
  if (status === "failed") return "red";
  if (status === "skipped") return "default";
  return "processing";
}

function externalSearchHasNoResults(run: DiscoverRun | null): boolean {
  const rawSummary = run?.stage_summaries?.external_search;
  if (!rawSummary || typeof rawSummary !== "object" || Array.isArray(rawSummary)) return false;
  const summary = rawSummary as { status?: unknown; candidate_count?: unknown };
  if (summary.status === "failed" || summary.status === "succeeded_empty") return true;
  return summary.status === "succeeded" && Number(summary.candidate_count ?? 0) === 0;
}

function verificationStatusLabel(status: string): string {
  switch (status) {
    case "selected": return "Selected · starting verification";
    case "imported_pending_parse": return "PDF downloaded · pipeline running";
    case "verified": return "Full text verified";
    case "no_pdf": return "No PDF available";
    case "import_failed": return "PDF download failed";
    case "verification_failed": return "Full-text verification failed";
    default: return "Not selected";
  }
}

function verificationActionLabel(status: string): string {
  if (status === "selected") return "Starting...";
  if (status === "imported_pending_parse") return "Processing...";
  if (status === "verified") return "Verified";
  if (["no_pdf", "import_failed", "verification_failed"].includes(status)) return "Retry verification";
  return "Import and verify";
}

function verificationActionDisabled(status: string): boolean {
  return ["selected", "imported_pending_parse", "verified"].includes(status);
}

function gateDetails(sourcePayload: Record<string, unknown>): { verified: boolean; confirmable: boolean; blockingMissing: string[]; warnings: string[]; missing: string[]; reason?: string } | null {
  const value = sourcePayload.gate;
  if (!value || typeof value !== "object") return null;
  const gate = value as { verified?: unknown; confirmable?: unknown; blocking_missing?: unknown; warnings?: unknown; missing?: unknown; reason?: unknown };
  const missing = Array.isArray(gate.missing) ? gate.missing.filter((item): item is string => typeof item === "string") : [];
  const blockingMissing = Array.isArray(gate.blocking_missing)
    ? gate.blocking_missing.filter((item): item is string => typeof item === "string")
    : missing.filter((item) => item !== "external verification did not complete");
  const warnings = Array.isArray(gate.warnings)
    ? gate.warnings.filter((item): item is string => typeof item === "string")
    : missing.filter((item) => item === "external verification did not complete");
  return {
    verified: gate.verified === true,
    confirmable: gate.confirmable === true || (blockingMissing.length === 0 && (gate.verified === true || warnings.length > 0)),
    blockingMissing,
    warnings,
    missing,
    reason: typeof gate.reason === "string" ? gate.reason : undefined,
  };
}

function opportunityStatus(item: ResearchOpportunity): string {
  const gate = gateDetails(item.source_payload);
  if (item.status === "needs_more_evidence" && gate?.confirmable) return "reviewable_with_warning";
  return item.status;
}

export default function DiscoverPage() {
  const { id: workspaceId, runId, opportunityId } = useParams<{ id: string; runId?: string; opportunityId?: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const { message, modal } = App.useApp();
  const screens = Grid.useBreakpoint();
  const [form] = Form.useForm();
  const [decisionForm] = Form.useForm();
  const [editForm] = Form.useForm();
  const [runs, setRuns] = useState<DiscoverRun[]>([]);
  const [runDetail, setRunDetail] = useState<Awaited<ReturnType<typeof discoverApi.getRun>> | null>(null);
  const [opportunities, setOpportunities] = useState<ResearchOpportunity[]>([]);
  const [selectedOpportunity, setSelectedOpportunity] = useState<OpportunityDetail | null>(null);
  const [runModalOpen, setRunModalOpen] = useState(false);
  const [decisionModalOpen, setDecisionModalOpen] = useState(false);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [decisionAction, setDecisionAction] = useState<"confirm" | "reject" | "defer">("confirm");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const selectedRunId = searchParams.get("run") ?? runId ?? null;
  const selectedOpportunityId = searchParams.get("opportunity") ?? opportunityId ?? null;
  const selectedRun = useMemo(() => runs.find((run) => run.id === selectedRunId) ?? runs[0] ?? null, [runs, selectedRunId]);

  const mergeDetail = useCallback((detail: Awaited<ReturnType<typeof discoverApi.getRun>>) => {
    setRunDetail(detail);
    setRuns((current) => current.map((run) => run.id === detail.id ? { ...run, ...detail } : run));
    setOpportunities((current) => {
      const merged = new Map(current.map((item) => [item.id, item]));
      detail.opportunities.forEach((item) => merged.set(item.id, item));
      return Array.from(merged.values());
    });
  }, []);

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
      if (current && current.id !== selectedRunId) {
        const next = new URLSearchParams(searchParams);
        next.set("run", current.id);
        setSearchParams(next, { replace: true });
      }
      if (current) mergeDetail(await discoverApi.getRun(workspaceId, current.id));
    } catch (error) {
      message.error(`Failed to load Discover: ${errorMessage(error)}`);
    } finally {
      setLoading(false);
    }
  }, [mergeDetail, message, searchParams, selectedRunId, setSearchParams, workspaceId]);

  useEffect(() => { void load(); }, [load]);

  const currentStatus = currentRunStatus(runDetail, selectedRun);
  useEffect(() => {
    const interval = pollingInterval(currentStatus);
    if (!interval) return undefined;
    const timer = window.setInterval(() => { void load(); }, interval);
    return () => window.clearInterval(timer);
  }, [currentStatus, load]);

  useEffect(() => {
    const claimText = searchParams.get("claim_text");
    if (searchParams.get("claim_item_id")) {
      setRunModalOpen(true);
      form.setFieldsValue({ topic: claimText ?? "" });
    }
  }, [form, searchParams]);

  const openRun = (runId: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("run", runId);
    setSearchParams(next);
  };

  const submitRun = async (values: Record<string, unknown>) => {
    if (!workspaceId) return;
    setSubmitting(true);
    try {
      const sourcePaperId = searchParams.get("source_paper_id") || undefined;
      const response = await discoverApi.createRun(workspaceId, {
        input: {
          topic: String(values.topic || "").trim() || undefined,
          claim_item_id: searchParams.get("claim_item_id") || undefined,
          paper_ids: sourcePaperId ? [sourcePaperId] : [],
          constraints: String(values.constraints || "").trim() || undefined,
          keywords: String(values.keywords || "").split(/[,\n]/).map((value) => value.trim()).filter(Boolean),
        },
        scope: { year_from: values.year_from ? Number(values.year_from) : undefined, year_to: values.year_to ? Number(values.year_to) : undefined, open_access_preferred: Boolean(values.open_access_preferred) },
        config: { max_opportunities: Number(values.max_opportunities || 3), top_k: 10, include_counter_evidence: true, use_reranker: true, use_judge: true },
      });
      message.success(`Discover run started (${response.run_id.slice(0, 8)})`);
      setRunModalOpen(false);
      form.resetFields();
      const next = new URLSearchParams(searchParams);
      next.delete("claim_item_id"); next.delete("claim_text"); next.delete("source_paper_id"); next.set("run", response.run_id);
      setSearchParams(next);
      await load();
    } catch (error) { message.error(`Could not start Discover: ${errorMessage(error)}`); }
    finally { setSubmitting(false); }
  };

  const openOpportunity = async (opportunityId: string) => {
    if (!workspaceId) return;
    try { setSelectedOpportunity(await discoverApi.getOpportunity(workspaceId, opportunityId)); }
    catch (error) { message.error(`Failed to load opportunity: ${errorMessage(error)}`); }
  };

  useEffect(() => {
    if (selectedOpportunityId) void openOpportunity(selectedOpportunityId);
  }, [selectedOpportunityId, workspaceId]);

  const openDecision = (action: "confirm" | "reject" | "defer") => {
    setDecisionAction(action);
    decisionForm.resetFields();
    setDecisionModalOpen(true);
  };

  const submitDecision = async (values: { note?: string; defer_condition?: string }) => {
    if (!workspaceId || !selectedOpportunity) return;
    setActionLoading(true);
    try {
      const item = selectedOpportunity.opportunity;
      if (decisionAction === "confirm") await discoverApi.confirm(workspaceId, item.id, selectedOpportunity.current_version?.id, values.note);
      if (decisionAction === "reject") await discoverApi.reject(workspaceId, item.id, values.note);
      if (decisionAction === "defer") await discoverApi.defer(workspaceId, item.id, values.note, values.defer_condition);
      setDecisionModalOpen(false);
      message.success(`Opportunity ${decisionAction}ed`);
      await openOpportunity(item.id); await load();
    } catch (error) { message.error(`Action failed: ${errorMessage(error)}`); }
    finally { setActionLoading(false); }
  };

  const submitEditConfirm = async (values: Record<string, unknown>) => {
    if (!workspaceId || !selectedOpportunity?.current_version) return;
    setActionLoading(true);
    try {
      const item = selectedOpportunity.opportunity;
      const { note, ...changes } = values;
      await discoverApi.editConfirm(workspaceId, item.id, { base_version_id: selectedOpportunity.current_version.id, changes, note: String(note || "") || undefined });
      setEditModalOpen(false);
      message.success("Opportunity edited and confirmed");
      await openOpportunity(item.id); await load();
    } catch (error) { message.error(`Edit failed: ${errorMessage(error)}`); }
    finally { setActionLoading(false); }
  };

  const convert = async () => {
    if (!workspaceId || !selectedOpportunity) return;
    setActionLoading(true);
    try { await discoverApi.convert(workspaceId, selectedOpportunity.opportunity.id); message.success("Research plan created"); await openOpportunity(selectedOpportunity.opportunity.id); await load(); }
    catch (error) { message.error(`Plan generation failed: ${errorMessage(error)}`); }
    finally { setActionLoading(false); }
  };

  const selectExternal = async (candidate: DiscoverExternalCandidate) => {
    if (!workspaceId || !runDetail) return;
    try { await discoverApi.selectExternal(workspaceId, runDetail.id, [candidate.id]); message.success("Paper selected; Discover is waiting for full-text processing"); await load(); }
    catch (error) { message.error(`Selection failed: ${errorMessage(error)}`); }
  };

  const skipExternalSelection = () => {
    if (!workspaceId || !runDetail) return;
    modal.confirm({
      title: "Skip external paper verification?",
      content: "Discover will continue using only evidence already available in this workspace. External candidates will not be imported or parsed, so novelty verification may be less complete.",
      okText: "Skip and continue",
      cancelText: "Keep selecting",
      onOk: async () => {
        setActionLoading(true);
        try {
          await discoverApi.skipExternalSelection(workspaceId, runDetail.id);
          message.success("External selection skipped; Discover is continuing with workspace knowledge");
          await load();
        } catch (error) {
          message.error(`Could not skip selection: ${errorMessage(error)}`);
        } finally {
          setActionLoading(false);
        }
      },
    });
  };

  const cancelRun = async () => {
    if (!workspaceId || !selectedRun) return;
    try { await discoverApi.cancelRun(workspaceId, selectedRun.id); message.success("Discover run cancelled"); await load(); }
    catch (error) { message.error(`Cancel failed: ${errorMessage(error)}`); }
  };
  const deleteRun = async (run: DiscoverRun) => {
    if (!workspaceId) return;
    try {
      await discoverApi.deleteRun(workspaceId, run.id);
      if (selectedRunId === run.id) {
        const next = new URLSearchParams(searchParams);
        next.delete("run");
        setSearchParams(next, { replace: true });
        setRunDetail(null);
      }
      message.success("Discover run deleted from history");
      await load();
    } catch (error) {
      message.error(`Delete failed: ${errorMessage(error)}`);
    }
  };

  if (!workspaceId) return <Empty description="Workspace not found" />;
  const stage = currentRunStage(runDetail, selectedRun);
  const stagePosition = stageIndex(stage);
  const activeRun = runDetail?.id === selectedRun?.id ? runDetail : selectedRun;
  const externalSearchError = externalSearchHasNoResults(activeRun);
  const selectedOpportunities = opportunities.filter((item) => !selectedRun || item.discover_run_id === selectedRun.id);

  return (
    <div style={{ padding: screens.md ? 24 : 12 }}>
      <Space direction="vertical" size={20} style={{ width: "100%" }}>
        <Space style={{ width: "100%", justifyContent: "space-between" }} wrap>
          <div><Title level={2} style={{ margin: 0 }}>Discover Workbench</Title><Text type="secondary">Evidence-grounded research opportunity discovery</Text></div>
          <Space wrap><Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>Refresh</Button>{selectedRun && !TERMINAL_RUN_STATUSES.has(selectedRun.status) && <Button danger icon={<CloseCircleOutlined />} onClick={() => void cancelRun()}>Cancel Run</Button>}<Button type="primary" icon={<PlusOutlined />} onClick={() => setRunModalOpen(true)}>New Discover Run</Button></Space>
        </Space>
        <div style={{ display: "grid", gridTemplateColumns: screens.md ? "minmax(230px, 0.28fr) minmax(0, 0.72fr)" : "minmax(0, 1fr)", gap: 20 }}>
          <Card title={`Run history (${runs.length})`} bodyStyle={{ padding: 0 }}>
            <List dataSource={runs} locale={{ emptyText: "No Discover runs yet" }} renderItem={(run) => <List.Item onClick={() => openRun(run.id)} actions={[<Popconfirm key="delete" title="Delete this Discover run?" description="The run will be hidden from history. Workspace papers, PDFs, opportunities, and plans will be preserved." okText="Delete" cancelText="Cancel" okButtonProps={{ danger: true }} onConfirm={() => void deleteRun(run)}><Button type="text" danger disabled={!TERMINAL_RUN_STATUSES.has(run.status)} title={TERMINAL_RUN_STATUSES.has(run.status) ? "Delete run" : "Cancel the run before deleting"} aria-label={`Delete ${run.input_topic || "Discover run"}`} icon={<DeleteOutlined />} onClick={(event) => event.stopPropagation()} /></Popconfirm>]} style={{ cursor: "pointer", padding: "14px 16px", background: selectedRun?.id === run.id ? "#f0f5ff" : undefined }}><List.Item.Meta avatar={<BulbOutlined />} title={<Text ellipsis>{run.input_topic || "Claim-driven discovery"}</Text>} description={<Space wrap><Tag color={statusColor(run.status)}>{run.status}</Tag><Text type="secondary">{Math.round(run.progress * 100)}%</Text><Text type="secondary">{run.stage.replaceAll("_", " ")}</Text></Space>} /></List.Item>} />
          </Card>
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            <Card title="Run overview" extra={selectedRun && <Space wrap><Tag color={statusColor(selectedRun.status)}>{selectedRun.status}</Tag>{selectedRun.status === "waiting_for_fulltext" && <Tag color="orange">Waiting for PDF pipeline</Tag>}</Space>}>
              {!selectedRun ? <Empty description="Start a run to inspect its progress and candidates" /> : <>
                <Descriptions size="small" column={{ xs: 1, sm: 2 }}><Descriptions.Item label="Topic">{selectedRun.input_topic || "Claim-driven"}</Descriptions.Item><Descriptions.Item label="Verification">{selectedRun.verification_status}</Descriptions.Item><Descriptions.Item label="Stage">{stage || "Unknown"}</Descriptions.Item><Descriptions.Item label="Selected opportunities">{selectedOpportunityCount(opportunities, selectedRun.id)}</Descriptions.Item></Descriptions>
                <Progress percent={Math.round((runDetail?.id === selectedRun.id ? runDetail.progress : selectedRun.progress) * 100)} status={selectedRun.status === "failed" ? "exception" : undefined} />
                {stagePosition < 0 ? <Tag color="red">Unknown stage: {stage || "missing"}</Tag> : <Steps size="small" current={stagePosition} responsive items={DISCOVER_STAGES.map((item) => { const label = item.replaceAll("_", " "); const failed = item === "external_search" && externalSearchError; return { status: failed ? "error" : undefined, title: <Tooltip title={failed ? "No papers found or external search failed" : label}><span>{label}</span></Tooltip> }; })} />}
                {selectedRun.status === "waiting_for_fulltext" && <Paragraph type="warning" style={{ marginTop: 16 }}>The selected paper is being parsed, indexed, and checked for EvidenceSpan. Synthesis is paused until the pipeline is ready.</Paragraph>}
                {selectedRun.status === "waiting_for_user" && stage === "external_selection" && <Alert style={{ marginTop: 16 }} type="info" showIcon message="External papers are ready for review" description={<Space direction="vertical" size={8}><Text>Select a paper for full-text verification, or continue with evidence already available in this workspace.</Text><Button onClick={skipExternalSelection} loading={actionLoading}>Skip external selection and continue</Button></Space>} />}
                {selectedRun.error_message && <Paragraph type="danger" style={{ marginTop: 16 }}>{selectedRun.error_message}</Paragraph>}
              </>}
            </Card>
            <Card size="small" title="Multi-agent handoff">
              {!runDetail?.agent_steps?.length ? <Empty description="The run records Planner → Evidence → External → Critic → Gate as it executes" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : <List size="small" dataSource={runDetail.agent_steps} renderItem={(step) => { const verdicts = step.stage === "critic" ? (step.details?.verdicts as Record<string, number> | undefined) : undefined; const narrowing = step.stage === "narrowing" ? (step.details?.narrowed as number | undefined) : undefined; return <List.Item><Space direction="vertical" size={2} style={{ width: "100%" }}><Space wrap><Tag color={agentStepColor(step.status)}>{step.status}</Tag><Text strong style={{ textTransform: "capitalize" }}>{step.stage.replaceAll("_", " ")}</Text><Text type="secondary">step {step.sequence}</Text></Space><Text type="secondary">{step.summary}</Text>{verdicts ? <Space wrap>{(["keep", "narrow", "reject"] as const).map((key) => <Tag key={key} color={key === "reject" ? "red" : key === "narrow" ? "orange" : "green"}>{key}: {verdicts[key] ?? 0}</Tag>)}</Space> : null}{narrowing ? <Text type="secondary">Focused counter-evidence pass narrowed {narrowing} candidate(s)</Text> : null}</Space></List.Item>; }} />}
            </Card>
            <Card title={`Opportunity candidates for this run (${selectedOpportunities.length})`}>
      {selectedOpportunities.length === 0 ? <Empty description={selectedRun?.status === "waiting_for_fulltext" ? "Candidates will appear after full-text verification" : "Candidates will appear after synthesis"} /> : <List dataSource={selectedOpportunities} renderItem={(item) => { const displayStatus = opportunityStatus(item); return <List.Item actions={[<Button key="open" type="link" onClick={() => void openOpportunity(item.id)}>Open details</Button>]}><List.Item.Meta title={<Space wrap><Text strong>{item.title}</Text><Tag color={statusColor(displayStatus)}>{displayStatus}</Tag></Space>} description={<Paragraph ellipsis={{ rows: 2 }} style={{ margin: 0 }}>{item.summary}</Paragraph>} /><Tag>{Math.round(item.confidence * 100)}% agent confidence</Tag></List.Item>; }} />}
            </Card>
            {runDetail?.external_candidates?.length ? <Card title="External candidates for verification" extra={selectedRun?.status === "waiting_for_user" && stage === "external_selection" ? <Button size="small" onClick={skipExternalSelection} loading={actionLoading}>Skip selection</Button> : null}><List size="small" dataSource={runDetail.external_candidates} renderItem={(candidate) => <List.Item actions={[<Button key="select" size="small" onClick={() => void selectExternal(candidate)} disabled={verificationActionDisabled(candidate.verification_status)}>{verificationActionLabel(candidate.verification_status)}</Button>]}><List.Item.Meta title={`${candidate.rank}. ${candidate.title}`} description={<Space wrap><Tag>{candidate.year || "Year unknown"}</Tag><Tag>{candidate.evidence_level}</Tag><Tag color={candidate.verification_status === "verified" ? "green" : candidate.verification_status === "verification_failed" ? "red" : "processing"}>{verificationStatusLabel(candidate.verification_status)}</Tag><Tag>{candidate.role}</Tag></Space>} /></List.Item>} /></Card> : null}
          </Space>
        </div>
      </Space>

      <Modal title="Run Discover" open={runModalOpen} onCancel={() => setRunModalOpen(false)} onOk={() => void form.submit()} okText="Run Discover" confirmLoading={submitting} width={640}>
        <Form form={form} layout="vertical" onFinish={(values) => void submitRun(values)} initialValues={{ max_opportunities: 3, topic: searchParams.get("claim_text") || undefined }}>
          {searchParams.get("claim_item_id") && <AlertText text={`Seed Claim: ${searchParams.get("claim_text") || "selected claim"}. Its source paper will be excluded from counter evidence.`} />}
          <Form.Item name="topic" label="Research topic or question" rules={[{ required: true, message: "Enter a topic or question" }]}><Input.TextArea rows={4} placeholder="e.g. Robust self-interpretable GNNs under distribution shift" /></Form.Item>
          <Form.Item name="keywords" label="Keywords"><Input placeholder="Separate keywords with commas" /></Form.Item>
          <Space wrap style={{ width: "100%" }}><Form.Item name="year_from" label="From"><Input type="number" placeholder="2020" /></Form.Item><Form.Item name="year_to" label="To"><Input type="number" placeholder="2026" /></Form.Item><Form.Item name="max_opportunities" label="Max candidates"><Select options={[1, 2, 3, 5].map((value) => ({ value, label: String(value) }))} /></Form.Item></Space>
          <Form.Item name="constraints" label="Constraints"><Input.TextArea rows={3} placeholder="Datasets, compute, time, or domain constraints" /></Form.Item>
          <Form.Item name="open_access_preferred" valuePropName="checked"><Checkbox>Prefer open-access papers for verification</Checkbox></Form.Item>
          <Text type="secondary">The run is asynchronous. Metadata-only evidence never counts as full-text support.</Text>
        </Form>
      </Modal>

      <Drawer title={selectedOpportunity?.opportunity.title} open={selectedOpportunity !== null} width="min(760px, 100vw)" onClose={() => setSelectedOpportunity(null)}>
        {selectedOpportunity && <OpportunityPanel workspaceId={workspaceId} detail={selectedOpportunity} loading={actionLoading} onAction={openDecision} onEdit={() => { const version = selectedOpportunity.current_version; if (version) { editForm.setFieldsValue({ ...version, note: "" }); setEditModalOpen(true); } }} onConvert={() => void convert()} />}
      </Drawer>

      <Modal title={`${decisionAction[0].toUpperCase()}${decisionAction.slice(1)} opportunity`} open={decisionModalOpen} confirmLoading={actionLoading} onCancel={() => setDecisionModalOpen(false)} onOk={() => void decisionForm.submit()}>
        <Form form={decisionForm} layout="vertical" onFinish={(values) => void submitDecision(values)}><Form.Item name="note" label={decisionAction === "confirm" ? "Review note" : "Reason"}><Input.TextArea rows={3} placeholder={decisionAction === "confirm" ? "Optional note" : "Explain this decision"} /></Form.Item>{decisionAction === "defer" && <Form.Item name="defer_condition" label="Review condition" rules={[{ required: true, message: "Describe when this should be reviewed again" }]}><Input.TextArea rows={3} placeholder="e.g. Revisit after importing two more full-text papers" /></Form.Item>}</Form>
      </Modal>
      <Modal title="Edit & Confirm opportunity" open={editModalOpen} width={720} confirmLoading={actionLoading} onCancel={() => setEditModalOpen(false)} onOk={() => void editForm.submit()}>
        <Form form={editForm} layout="vertical" onFinish={(values) => void submitEditConfirm(values)}><Form.Item name="title" label="Title" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="problem_statement" label="Problem statement" rules={[{ required: true }]}><Input.TextArea rows={3} /></Form.Item><Form.Item name="research_scope" label="Research scope"><Input.TextArea rows={2} /></Form.Item><Form.Item name="why_existing_work_is_insufficient" label="Why existing work is insufficient"><Input.TextArea rows={3} /></Form.Item><Form.Item name="candidate_research_question" label="Research question"><Input.TextArea rows={2} /></Form.Item><Form.Item name="candidate_hypothesis" label="Falsifiable hypothesis"><Input.TextArea rows={2} /></Form.Item><Form.Item name="note" label="Edit note"><Input.TextArea rows={2} /></Form.Item></Form>
      </Modal>
    </div>
  );
}

function AlertText({ text }: { text: string }) {
  return <Paragraph type="secondary" style={{ background: "#f5f5f5", padding: 10, borderRadius: 6 }}>{text}</Paragraph>;
}

function OpportunityPanel({ workspaceId, detail, loading, onAction, onEdit, onConvert }: { workspaceId: string; detail: OpportunityDetail; loading: boolean; onAction: (action: "confirm" | "reject" | "defer") => void; onEdit: () => void; onConvert: () => void }) {
  const version = detail.current_version;
  const gate = gateDetails(detail.opportunity.source_payload);
  const confirmable = gate?.confirmable ?? detail.opportunity.status !== "needs_more_evidence";
  const supporting = detail.evidence.filter((item) => item.relation === "supports");
  const similar = detail.evidence.filter((item) => item.relation === "similar");
  const counter = detail.evidence.filter((item) => ["contradicts", "qualifies", "overlaps", "unknown"].includes(item.relation));
  return <Space direction="vertical" style={{ width: "100%" }}>
    <Space wrap><Tag color={statusColor(opportunityStatus(detail.opportunity))}>{opportunityStatus(detail.opportunity)}</Tag><Tag color={statusColor(version?.verification_status || "unverified")}>{version?.verification_status || "unverified"}</Tag><Tag>Coverage {Math.round((version?.evidence_coverage || 0) * 100)}%</Tag><Tag>Agent confidence {Math.round(detail.opportunity.confidence * 100)}%</Tag></Space>
    {!confirmable && <Alert type="warning" showIcon message="This opportunity cannot be confirmed yet" description={gate?.blockingMissing.length ? <List size="small" dataSource={gate.blockingMissing} renderItem={(item) => <List.Item>{item}</List.Item>} /> : gate?.reason || "The core Evidence Gate has not been satisfied."} />}
    {confirmable && gate?.warnings.length ? <Alert type="info" showIcon message="Confirmable with verification warnings" description={<List size="small" dataSource={gate.warnings} renderItem={(item) => <List.Item>{item}</List.Item>} />} /> : null}
    <Divider orientation="left">Overview</Divider><Paragraph>{version?.problem_statement || detail.opportunity.summary}</Paragraph>
    <Descriptions column={1} size="small"><Descriptions.Item label="Scope">{version?.research_scope || "—"}</Descriptions.Item><Descriptions.Item label="Why existing work is insufficient">{version?.why_existing_work_is_insufficient || detail.opportunity.rationale}</Descriptions.Item><Descriptions.Item label="Research question">{version?.candidate_research_question || "—"}</Descriptions.Item><Descriptions.Item label="Hypothesis">{version?.candidate_hypothesis || "—"}</Descriptions.Item></Descriptions>
    <EvidenceGroup workspaceId={workspaceId} title={`Supporting evidence (${supporting.length})`} items={supporting} empty="No span-backed supporting evidence" />
    <EvidenceGroup workspaceId={workspaceId} title={`Similar work (${similar.length})`} items={similar} empty="No similar work saved" />
    <EvidenceGroup workspaceId={workspaceId} title={`Counter / qualifying evidence (${counter.length})`} items={counter} empty="No counter evidence saved" />
    <Divider orientation="left">Validation plan</Divider><List size="small" dataSource={(version?.candidate_validation_plan?.steps as string[]) || []} renderItem={(step) => <List.Item>{step}</List.Item>} locale={{ emptyText: "No structured validation steps" }} />
    <Divider orientation="left">Human decision</Divider><Space wrap><Button danger onClick={() => onAction("reject")} loading={loading}>Reject</Button><Button onClick={() => onAction("defer")} loading={loading}>Defer</Button><Button onClick={onEdit} loading={loading} disabled={!confirmable}>Edit & Confirm</Button><Button type="primary" onClick={() => onAction("confirm")} loading={loading} disabled={!confirmable}>Confirm</Button>{["confirmed", "edited_confirmed"].includes(detail.opportunity.status) && <Button onClick={onConvert} loading={loading}>Generate Research Plan</Button>}</Space>
    {detail.plan && <Card size="small" title="Research Plan created"><Paragraph>{detail.plan.research_question}</Paragraph></Card>}
  </Space>;
}

function EvidenceGroup({ workspaceId, title, items, empty }: { workspaceId: string; title: string; items: OpportunityDetail["evidence"]; empty: string }) {
  return <Card size="small" title={title}><List size="small" dataSource={items} locale={{ emptyText: empty }} renderItem={(evidence) => <List.Item><Space direction="vertical" style={{ width: "100%" }}><Space wrap><Tag color={evidence.relation === "contradicts" ? "red" : evidence.relation === "supports" ? "green" : "blue"}>{evidence.relation}</Tag><Tag>{evidence.source_scope}</Tag><Tag color={evidence.evidence_level === "full_text" ? "green" : "orange"}>{evidence.evidence_level}</Tag></Space><Text>{evidence.display_excerpt || "No excerpt"}</Text><OpportunityEvidenceViewer workspaceId={workspaceId} evidence={evidence} /></Space></List.Item>} /></Card>;
}
