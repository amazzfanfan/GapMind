import { useCallback, useEffect, useMemo, useState } from "react";
import {
  App,
  Button,
  Card,
  Descriptions,
  Divider,
  Drawer,
  Empty,
  Input,
  InputNumber,
  List,
  Modal,
  Select,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import {
  AppstoreOutlined,
  BarsOutlined,
  FileSearchOutlined,
  ReloadOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import knowledgeApi from "../api/knowledge";
import type {
  EvidenceSpan,
  KnowledgeItem,
  KnowledgeRelation,
} from "../api/types/knowledge";
import paperApi from "../api/paper";
import type { Paper } from "../api/types/domain";
import EvidenceViewer from "./EvidenceViewer";
import DiscoverOpportunity from "./DiscoverOpportunity";

const { Paragraph, Text } = Typography;
type WorkbenchLayout = "single" | "double";
const LAYOUT_STORAGE_KEY = "gapmind.knowledge-workbench.layout";

const TYPE_OPTIONS = [
  ["method", "Method"],
  ["task", "Task"],
  ["dataset", "Dataset"],
  ["claim", "Claim"],
  ["limitation", "Limitation"],
  ["evidence", "Evidence"],
] as const;

const STATUS_OPTIONS = [
  ["extracted_candidate", "Extracted candidate"],
  ["evidence_backed_proposal", "Evidence-backed proposal"],
  ["human_confirmed", "Human confirmed"],
  ["rejected", "Rejected"],
] as const;

function errorMessage(error: unknown): string {
  const detail = (
    error as { response?: { data?: { detail?: { message?: string } } } }
  ).response?.data?.detail;
  return detail?.message || (error as Error).message || "Request failed";
}

function typeColor(type: string): string {
  const colors: Record<string, string> = {
    method: "blue",
    task: "green",
    dataset: "orange",
    claim: "purple",
    limitation: "red",
    evidence: "cyan",
  };
  return colors[type] ?? "default";
}

function statusColor(status: string): string {
  if (status === "human_confirmed") return "green";
  if (status === "rejected" || status === "invalidated") return "red";
  if (status === "evidence_backed_proposal") return "blue";
  return "gold";
}

function contentPreview(content: Record<string, unknown> | undefined): string {
  const preferred = [
    "statement",
    "description",
    "key_idea",
    "problem_addressed",
    "limitation_type",
  ];
  for (const key of preferred) {
    const value = content?.[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return JSON.stringify(content ?? {});
}

export default function KnowledgeWorkbench({
  workspaceId,
}: {
  workspaceId: string;
}) {
  const { message } = App.useApp();
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>();
  const [statusFilter, setStatusFilter] = useState<string>();
  const [paperFilter, setPaperFilter] = useState<string>();
  const [minConfidence, setMinConfidence] = useState<number>();
  const [selectedItem, setSelectedItem] = useState<KnowledgeItem | null>(null);
  const [evidence, setEvidence] = useState<EvidenceSpan[]>([]);
  const [relations, setRelations] = useState<KnowledgeRelation[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [editName, setEditName] = useState("");
  const [editContent, setEditContent] = useState("{}");
  const [reviewNote, setReviewNote] = useState("");
  const [layout, setLayout] = useState<WorkbenchLayout>(() =>
    window.localStorage.getItem(LAYOUT_STORAGE_KEY) === "double" ? "double" : "single",
  );

  const paperMap = useMemo(
    () => new Map(papers.map((paper) => [paper.id, paper.title])),
    [papers],
  );

  const loadItems = useCallback(async () => {
    setLoading(true);
    try {
      const response = await knowledgeApi.listItems(workspaceId, {
        type: typeFilter,
        status: statusFilter,
        paper_id: paperFilter,
        q: appliedQuery || undefined,
        min_confidence: minConfidence,
      });
      setItems(response.items ?? []);
      setTotal(response.total);
    } catch (error) {
      message.error(`Failed to load knowledge: ${errorMessage(error)}`);
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [appliedQuery, message, minConfidence, paperFilter, statusFilter, typeFilter, workspaceId]);

  useEffect(() => {
    void loadItems();
  }, [loadItems]);

  useEffect(() => {
    paperApi
      .list(workspaceId, { limit: 200 })
      .then((response) => setPapers(response.items))
      .catch(() => setPapers([]));
  }, [workspaceId]);

  const openDetail = async (item: KnowledgeItem) => {
    setSelectedItem(item);
    setEditName(item.canonical_name);
    setEditContent(JSON.stringify(item.content, null, 2));
    setReviewNote(item.review_note ?? "");
    setEvidence([]);
    setRelations([]);
    setDetailLoading(true);
    try {
      const [evidenceResponse, relationResponse] = await Promise.all([
        knowledgeApi.listEvidence(workspaceId, item.id),
        knowledgeApi.listRelations(workspaceId, { item_id: item.id }),
      ]);
      setEvidence(evidenceResponse.items ?? []);
      setRelations(relationResponse.items ?? []);
    } catch (error) {
      message.error(`Failed to load evidence: ${errorMessage(error)}`);
    } finally {
      setDetailLoading(false);
    }
  };

  const submitReview = async (action: "confirm" | "edit" | "reject") => {
    if (!selectedItem) return;
    setReviewing(true);
    try {
      let content: Record<string, unknown> | undefined;
      if (action === "edit") {
        content = JSON.parse(editContent) as Record<string, unknown>;
      }
      const updated = await knowledgeApi.reviewItem(workspaceId, selectedItem.id, {
        action,
        canonical_name: action === "edit" ? editName.trim() : undefined,
        content,
        note: reviewNote.trim() || undefined,
      });
      setSelectedItem(updated);
      setReviewOpen(false);
      message.success(action === "reject" ? "Knowledge item rejected" : "Knowledge item reviewed");
      await loadItems();
    } catch (error) {
      message.error(`Review failed: ${error instanceof SyntaxError ? "Content must be valid JSON" : errorMessage(error)}`);
    } finally {
      setReviewing(false);
    }
  };

  const clearFilters = () => {
    setQuery("");
    setAppliedQuery("");
    setTypeFilter(undefined);
    setStatusFilter(undefined);
    setPaperFilter(undefined);
    setMinConfidence(undefined);
  };

  const toggleLayout = () => {
    setLayout((current) => {
      const next = current === "single" ? "double" : "single";
      window.localStorage.setItem(LAYOUT_STORAGE_KEY, next);
      return next;
    });
  };

  return (
    <Card
      title="Knowledge Workbench"
      extra={
        <Space>
          <Text type="secondary">{total} items</Text>
          <Tooltip title={layout === "single" ? "Switch to two columns" : "Switch to one column"}>
            <Button
              icon={layout === "single" ? <AppstoreOutlined /> : <BarsOutlined />}
              onClick={toggleLayout}
            >
              {layout === "single" ? "Two columns" : "Single column"}
            </Button>
          </Tooltip>
          <Button icon={<ReloadOutlined />} onClick={() => void loadItems()} loading={loading}>
            Refresh
          </Button>
        </Space>
      }
    >
      <Space wrap style={{ width: "100%", marginBottom: 16 }}>
        <Input
          allowClear
          value={query}
          style={{ width: 260 }}
          prefix={<SearchOutlined />}
          placeholder="Search knowledge names"
          onChange={(event) => setQuery(event.target.value)}
          onPressEnter={() => setAppliedQuery(query.trim())}
        />
        <Select
          allowClear
          style={{ width: 160 }}
          placeholder="Type"
          value={typeFilter}
          options={TYPE_OPTIONS.map(([value, label]) => ({ value, label }))}
          onChange={setTypeFilter}
        />
        <Select
          allowClear
          style={{ width: 210 }}
          placeholder="Status"
          value={statusFilter}
          options={STATUS_OPTIONS.map(([value, label]) => ({ value, label }))}
          onChange={setStatusFilter}
        />
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          style={{ width: 260 }}
          placeholder="Source paper"
          value={paperFilter}
          options={papers.map((paper) => ({ value: paper.id, label: paper.title }))}
          onChange={setPaperFilter}
        />
        <InputNumber
          min={0}
          max={1}
          step={0.1}
          placeholder="Min confidence"
          value={minConfidence}
          onChange={(value) => setMinConfidence(value ?? undefined)}
        />
        <Button onClick={() => setAppliedQuery(query.trim())}>Apply</Button>
        <Button onClick={clearFilters}>Clear</Button>
      </Space>

      {loading && items.length === 0 ? (
        <div style={{ textAlign: "center", padding: 48 }}><Spin /></div>
      ) : items.length === 0 ? (
        <Empty description="No extracted knowledge matches these filters" />
      ) : (
        <div className={`gm-knowledge-card-grid is-${layout}`} aria-busy={loading}>
          {items.map((item) => {
            const sourcePaper = item.paper_id ? paperMap.get(item.paper_id) ?? item.paper_id : "No source paper";
            return (
              <article
                key={item.id}
                className="gm-knowledge-item-card"
                role="button"
                tabIndex={0}
                onClick={() => void openDetail(item)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    void openDetail(item);
                  }
                }}
              >
                <div className="gm-knowledge-item-meta">
                  <Space size={[6, 6]} wrap>
                    <Tag color={typeColor(item.type)}>{item.type}</Tag>
                    <Tag color={statusColor(item.status)}>{item.status}</Tag>
                  </Space>
                  <Text type="secondary">{Math.round(item.confidence * 100)}%</Text>
                </div>
                <Typography.Title level={5} className="gm-knowledge-item-name">
                  {item.canonical_name}
                </Typography.Title>
                <Paragraph type="secondary" className="gm-knowledge-item-content">
                  {contentPreview(item.content)}
                </Paragraph>
                <div className="gm-knowledge-item-footer">
                  <div className="gm-knowledge-item-source">
                    <Text type="secondary">Source paper</Text>
                    <Text title={sourcePaper}>{sourcePaper}</Text>
                  </div>
                  <Tooltip title="Open details and review">
                    <FileSearchOutlined className="gm-knowledge-item-detail-icon" />
                  </Tooltip>
                </div>
              </article>
            );
          })}
        </div>
      )}

      <Drawer
        title={selectedItem?.canonical_name}
        open={selectedItem !== null}
        width={560}
        onClose={() => setSelectedItem(null)}
      >
        {selectedItem && (
          detailLoading ? <div style={{ textAlign: "center", padding: 48 }}><Spin /></div> : (
            <>
              <Space wrap>
                <Tag color={typeColor(selectedItem.type)}>{selectedItem.type}</Tag>
                <Tag color={statusColor(selectedItem.status)}>{selectedItem.status}</Tag>
                <Tag>{Math.round(selectedItem.confidence * 100)}% confidence</Tag>
              </Space>
              <Descriptions column={1} size="small" style={{ marginTop: 16 }}>
                <Descriptions.Item label="Source paper">
                  {selectedItem.paper_id ? paperMap.get(selectedItem.paper_id) ?? selectedItem.paper_id : "—"}
                </Descriptions.Item>
                <Descriptions.Item label="Created by">{selectedItem.created_by}</Descriptions.Item>
                <Descriptions.Item label="Extraction run">{selectedItem.extraction_run_id ?? "—"}</Descriptions.Item>
              </Descriptions>
              <Divider orientation="left">Structured content</Divider>
              <pre style={{ whiteSpace: "pre-wrap", background: "#f7f8fa", padding: 12, borderRadius: 6 }}>
                {JSON.stringify(selectedItem.content, null, 2)}
              </pre>

              <Divider orientation="left">Evidence ({evidence.length})</Divider>
              <List
                size="small"
                dataSource={evidence}
                locale={{ emptyText: "No evidence spans" }}
                renderItem={(span: EvidenceSpan) => (
                  <List.Item>
                    <Space direction="vertical" style={{ width: "100%" }}>
                      <Paragraph style={{ margin: 0 }}><Tag color={span.relation === "contradicts" ? "red" : "green"}>{span.relation}</Tag>{span.text || "No evidence text"}</Paragraph>
                      {span.artifact_id && <EvidenceViewer workspaceId={workspaceId} itemId={selectedItem.id} span={span} />}
                    </Space>
                  </List.Item>
                )}
              />

              <Divider orientation="left">Relations ({relations.length})</Divider>
              <List
                size="small"
                dataSource={relations}
                locale={{ emptyText: "No relations" }}
                renderItem={(relation: KnowledgeRelation) => (
                  <List.Item>
                    <Text>
                      {relation.source_id === selectedItem.id ? "→" : "←"} {relation.relation_type} · {Math.round(relation.confidence * 100)}%
                    </Text>
                  </List.Item>
                )}
              />
              <Divider orientation="left">Human review</Divider>
              <Space wrap>
                <Button type="primary" onClick={() => void submitReview("confirm")} loading={reviewing}>Confirm</Button>
                <Button onClick={() => { setEditName(selectedItem.canonical_name); setEditContent(JSON.stringify(selectedItem.content, null, 2)); setReviewOpen(true); }}>Edit</Button>
                <Button danger onClick={() => void submitReview("reject")} loading={reviewing}>Reject</Button>
                {selectedItem.type === "claim" && <DiscoverOpportunity workspaceId={workspaceId} item={selectedItem} />}
              </Space>
            </>
          )
        )}
      </Drawer>
      <Modal
        title="Edit Knowledge Item"
        open={reviewOpen}
        okText="Save and confirm"
        confirmLoading={reviewing}
        onOk={() => void submitReview("edit")}
        onCancel={() => setReviewOpen(false)}
        width={720}
      >
        <Typography.Text strong>Name</Typography.Text>
        <Input value={editName} onChange={(event) => setEditName(event.target.value)} style={{ margin: "8px 0 16px" }} />
        <Typography.Text strong>Structured content (JSON)</Typography.Text>
        <Input.TextArea value={editContent} onChange={(event) => setEditContent(event.target.value)} autoSize={{ minRows: 10, maxRows: 20 }} style={{ marginTop: 8, fontFamily: "monospace" }} />
        <Typography.Text strong style={{ display: "block", marginTop: 16 }}>Review note</Typography.Text>
        <Input.TextArea value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} autoSize={{ minRows: 2, maxRows: 5 }} style={{ marginTop: 8 }} />
      </Modal>
    </Card>
  );
}
