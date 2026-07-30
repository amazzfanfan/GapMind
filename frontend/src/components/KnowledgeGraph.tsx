import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  Input,
  InputNumber,
  Pagination,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import {
  ApartmentOutlined,
  CompressOutlined,
  ExpandOutlined,
  FilterOutlined,
  InfoCircleOutlined,
  ReloadOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import CytoscapeComponent from "react-cytoscapejs";
import type { Core } from "cytoscape";
import { useNavigate } from "react-router-dom";
import knowledgeApi from "../api/knowledge";
import type {
  KnowledgeGraphEdge,
  KnowledgeGraphNode,
} from "../api/types/knowledge";

const { Paragraph, Text } = Typography;

const TYPE_OPTIONS = [
  ["method", "Method"],
  ["task", "Task"],
  ["dataset", "Dataset"],
  ["claim", "Claim"],
  ["limitation", "Limitation"],
] as const;

const RELATION_OPTIONS = [
  "supports", "contradicts", "qualifies", "evaluates_on", "extends",
  "compares_with", "related_to", "contains", "canonicalizes", "mentioned_in",
  "refers_to", "evidences",
];

const TYPE_COLORS: Record<string, string> = {
  method: "#1677ff", task: "#52c41a", dataset: "#fa8c16", claim: "#722ed1",
  limitation: "#f5222d", evidence: "#13c2c2", paper: "#595959",
  canonical_entity: "#13c2c2", paper_mention: "#faad14",
};

const RELATION_COLORS: Record<string, string> = {
  supports: "#52c41a", contradicts: "#f5222d", qualifies: "#fa8c16",
  evaluates_on: "#1677ff", extends: "#722ed1", compares_with: "#13c2c2",
  related_to: "#8c8c8c", contains: "#595959", canonicalizes: "#13c2c2",
  mentioned_in: "#faad14", refers_to: "#faad14", evidences: "#faad14",
};

type FocusMode = "all" | "claims" | "papers" | "entities";

function errorMessage(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: { message?: string } } } })
    .response?.data?.detail;
  return detail?.message || (error as Error).message || "Request failed";
}

function nodeShape(node: KnowledgeGraphNode): string {
  if (node.node_kind === "paper") return "round-rectangle";
  if (node.node_kind === "canonical_entity") return "diamond";
  if (node.node_kind === "paper_mention") return "ellipse";
  return "ellipse";
}

export default function KnowledgeGraph({ workspaceId }: { workspaceId: string }) {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const cyRef = useRef<Core | null>(null);
  const [nodes, setNodes] = useState<KnowledgeGraphNode[]>([]);
  const [edges, setEdges] = useState<KnowledgeGraphEdge[]>([]);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>();
  const [relationFilter, setRelationFilter] = useState<string>();
  const [minConfidence, setMinConfidence] = useState<number>();
  const [truncated, setTruncated] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [focusMode, setFocusMode] = useState<FocusMode>("all");
  const [showEvidenceNodes, setShowEvidenceNodes] = useState(false);
  const [showRelationLabels, setShowRelationLabels] = useState(false);
  const pageSize = 50;

  const selectedNode = nodes.find((node) => node.id === selectedNodeId) ?? null;

  const visibleNodeIds = useMemo(() => {
    let focused = nodes;
    if (focusMode === "claims") focused = nodes.filter((node) => node.type === "claim");
    if (focusMode === "papers") focused = nodes.filter((node) => node.node_kind === "paper");
    if (focusMode === "entities") focused = nodes.filter((node) => node.node_kind === "canonical_entity");

    const focusedIds = new Set(focused.map((node) => node.id));
    if (focusMode !== "all") {
      edges.forEach((edge) => {
        if (focusedIds.has(edge.source)) focusedIds.add(edge.target);
        if (focusedIds.has(edge.target)) focusedIds.add(edge.source);
      });
    }
    return new Set(
      nodes
        .filter((node) => showEvidenceNodes || node.node_kind !== "paper_mention")
        .filter((node) => focusedIds.has(node.id))
        .map((node) => node.id),
    );
  }, [edges, focusMode, nodes, showEvidenceNodes]);

  const visibleNodes = useMemo(
    () => nodes.filter((node) => visibleNodeIds.has(node.id)),
    [nodes, visibleNodeIds],
  );
  const visibleEdges = useMemo(
    () => edges.filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target)),
    [edges, visibleNodeIds],
  );
  const activeFilterCount = [
    appliedQuery,
    typeFilter,
    relationFilter,
    minConfidence !== undefined,
  ].filter(Boolean).length;

  const loadGraph = useCallback(async () => {
    setLoading(true);
    try {
      const response = await knowledgeApi.graph(workspaceId, {
        type: typeFilter,
        relation_type: relationFilter,
        q: appliedQuery || undefined,
        min_confidence: minConfidence,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      });
      setNodes(response.nodes);
      setEdges(response.edges);
      setTruncated(response.truncated);
      setSelectedNodeId(null);
    } catch (error) {
      message.error(`Failed to load knowledge graph: ${errorMessage(error)}`);
      setNodes([]);
      setEdges([]);
    } finally {
      setLoading(false);
    }
  }, [appliedQuery, message, minConfidence, page, relationFilter, typeFilter, workspaceId]);

  useEffect(() => { void loadGraph(); }, [loadGraph]);

  const elements = useMemo(
    () => [
      ...visibleNodes.map((node) => ({
        data: {
          id: node.id,
          label: node.label,
          color: TYPE_COLORS[node.type] ?? "#8c8c8c",
          shape: nodeShape(node),
          type: node.type,
          node_kind: node.node_kind,
        },
      })),
      ...visibleEdges.map((edge) => ({
        data: {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          label: showRelationLabels ? edge.relation_type : "",
          color: RELATION_COLORS[edge.relation_type] ?? "#8c8c8c",
        },
      })),
    ],
    [showRelationLabels, visibleEdges, visibleNodes],
  );

  const stylesheet = useMemo(() => [
    {
      selector: "node",
      style: {
        label: "data(label)", "background-color": "data(color)",
        shape: "data(shape)", "border-color": "#ffffff", "border-width": 2,
        color: "#1f1f1f", "font-size": 10, "text-wrap": "wrap",
        "text-max-width": 140, "text-valign": "center", "text-halign": "center",
        width: 48, height: 48,
      },
    },
    {
      selector: "node[node_kind = 'paper']",
      style: { width: 110, height: 44, "font-size": 11, "font-weight": "bold" },
    },
    {
      selector: "node[node_kind = 'canonical_entity']",
      style: { width: 66, height: 66, "font-size": 10, "border-width": 3 },
    },
    {
      selector: "node[node_kind = 'paper_mention']",
      style: { width: 38, height: 38, "font-size": 8, opacity: 0.72 },
    },
    {
      selector: "node[type = 'claim']",
      style: { width: 64, height: 64, "border-width": 4, "font-weight": "bold" },
    },
    {
      selector: "edge",
      style: {
        label: "data(label)", "line-color": "data(color)",
        "target-arrow-color": "data(color)", "target-arrow-shape": "triangle",
        "curve-style": "bezier", "font-size": 8, color: "#595959",
        "text-background-color": "#ffffff", "text-background-opacity": 1,
      },
    },
    { selector: ":selected", style: { "border-color": "#000000", "border-width": 4 } },
  ], []);

  const handleCy = useCallback((cy: Core) => {
    cyRef.current = cy;
    cy.removeAllListeners();
    cy.on("tap", "node", (event) => setSelectedNodeId(event.target.id()));
  }, []);

  const expandSelected = async () => {
    if (!selectedNode) return;
    try {
      const response = await knowledgeApi.graphNeighbors(workspaceId, selectedNode.id, {
        depth: 1,
        relation_type: relationFilter,
      });
      setNodes((current) => {
        const merged = new Map(current.map((node) => [node.id, node]));
        response.nodes.forEach((node) => merged.set(node.id, node));
        return [...merged.values()];
      });
      setEdges((current) => {
        const merged = new Map(current.map((edge) => [edge.id, edge]));
        response.edges.forEach((edge) => merged.set(edge.id, edge));
        return [...merged.values()];
      });
      message.success("Neighbor nodes loaded");
    } catch (error) {
      message.error(`Failed to expand neighbors: ${errorMessage(error)}`);
    }
  };

  const applyFilters = () => {
    setPage(1);
    setAppliedQuery(query.trim());
  };

  const resetView = () => {
    setQuery("");
    setAppliedQuery("");
    setTypeFilter(undefined);
    setRelationFilter(undefined);
    setMinConfidence(undefined);
    setFocusMode("all");
    setShowEvidenceNodes(false);
    setShowRelationLabels(false);
    setPage(1);
  };

  const connectedEdges = selectedNode
    ? visibleEdges.filter((edge) => edge.source === selectedNode.id || edge.target === selectedNode.id)
    : [];

  return (
    <Card
      title="Knowledge Graph"
      extra={<Space><Text type="secondary">{visibleNodes.length} shown · {visibleEdges.length} relations</Text><Button icon={<ReloadOutlined />} onClick={() => void loadGraph()} loading={loading}>Refresh</Button></Space>}
    >
      <Space wrap style={{ width: "100%", marginBottom: 16 }}>
        <Select
          value={focusMode}
          style={{ width: 180 }}
          prefix={<FilterOutlined />}
          options={[
            { value: "all", label: "All graph" },
            { value: "claims", label: "Focus: Claims" },
            { value: "papers", label: "Focus: Papers" },
            { value: "entities", label: "Focus: Entities" },
          ]}
          onChange={(value: FocusMode) => setFocusMode(value)}
        />
        <Input allowClear style={{ width: 240 }} placeholder="Search node names" value={query} onChange={(event) => setQuery(event.target.value)} onPressEnter={applyFilters} />
        <Select allowClear style={{ width: 160 }} placeholder="Knowledge type" value={typeFilter} options={TYPE_OPTIONS.map(([value, label]) => ({ value, label }))} onChange={(value) => { setTypeFilter(value); setPage(1); }} />
        <Select allowClear style={{ width: 190 }} placeholder="Relation type" value={relationFilter} options={RELATION_OPTIONS.map((value) => ({ value, label: value }))} onChange={(value) => { setRelationFilter(value); setPage(1); }} />
        <InputNumber min={0} max={1} step={0.1} placeholder="Min confidence" value={minConfidence} onChange={(value) => { setMinConfidence(value ?? undefined); setPage(1); }} />
        <Button onClick={applyFilters}>Apply</Button>
        <Button icon={<SettingOutlined />} onClick={resetView}>Reset view</Button>
        <Button icon={<CompressOutlined />} onClick={() => cyRef.current?.fit(undefined, 30)}>Fit</Button>
        <Button icon={<ApartmentOutlined />} onClick={() => cyRef.current?.layout({ name: "cose", animate: true, padding: 30 }).run()}>Relayout</Button>
      </Space>

      <Space wrap style={{ width: "100%", marginBottom: 16 }}>
        <Checkbox checked={showEvidenceNodes} onChange={(event) => setShowEvidenceNodes(event.target.checked)}>
          Show evidence mentions
        </Checkbox>
        <Checkbox checked={showRelationLabels} onChange={(event) => setShowRelationLabels(event.target.checked)}>
          Show relation labels
        </Checkbox>
        <Text type="secondary"><InfoCircleOutlined /> Click a node to inspect details; use Expand neighbors for more context.</Text>
      </Space>

      <Space wrap style={{ minHeight: 26, marginBottom: 8 }}>
        {activeFilterCount > 0 && <Text type="secondary">Active filters:</Text>}
        {appliedQuery && <Tag closable onClose={() => { setQuery(""); setAppliedQuery(""); setPage(1); }}>Name: {appliedQuery}</Tag>}
        {typeFilter && <Tag closable onClose={() => { setTypeFilter(undefined); setPage(1); }}>Type: {typeFilter}</Tag>}
        {relationFilter && <Tag closable onClose={() => { setRelationFilter(undefined); setPage(1); }}>Relation: {relationFilter}</Tag>}
        {minConfidence !== undefined && <Tag closable onClose={() => { setMinConfidence(undefined); setPage(1); }}>Confidence ≥ {minConfidence}</Tag>}
      </Space>

      {truncated && <Alert type="info" showIcon message="当前只加载了部分节点。可以翻页，或点击节点后展开邻居。" style={{ marginBottom: 16 }} />}

      {loading && visibleNodes.length === 0 ? <div style={{ textAlign: "center", padding: 48 }}><Spin /></div> : visibleNodes.length === 0 ? <Empty description="No knowledge graph data matches these filters" /> : (
        <div style={{ border: "1px solid #f0f0f0", borderRadius: 8, overflow: "hidden" }}>
          <CytoscapeComponent elements={elements} stylesheet={stylesheet} layout={{ name: "cose", animate: false, padding: 30 }} cy={handleCy} style={{ width: "100%", height: "620px", background: "#fafafa" }} />
        </div>
      )}

      <Space wrap style={{ marginTop: 16 }}>
        {Object.entries(TYPE_COLORS).map(([value, color]) => <Tag key={value} color={color}>{value}</Tag>)}
        <Text type="secondary">Paper=矩形，CanonicalEntity=菱形，Mention 默认隐藏；点击节点可展开邻居。</Text>
      </Space>
      <Pagination current={page} pageSize={pageSize} total={truncated ? page * pageSize + 1 : page * pageSize} showSizeChanger={false} hideOnSinglePage={!truncated && page === 1} onChange={(next) => setPage(next)} style={{ marginTop: 16, textAlign: "right" }} />

      <Drawer title={selectedNode?.label} open={selectedNode !== null} width={500} onClose={() => setSelectedNodeId(null)}>
        {selectedNode && <>
          <Space wrap>
            <Tag color={TYPE_COLORS[selectedNode.type]}>{selectedNode.node_kind}</Tag>
            <Tag>{Math.round(selectedNode.confidence * 100)}% confidence</Tag>
            <Tag>{selectedNode.status}</Tag>
          </Space>
          <Button type="primary" icon={<ExpandOutlined />} onClick={() => void expandSelected()} style={{ marginTop: 16 }}>Expand neighbors</Button>
          {selectedNode.node_kind === "knowledge" && (
            <Button onClick={() => navigate(`/workspaces/${workspaceId}/knowledge`)} style={{ marginTop: 16, marginLeft: 8 }}>
              Open in Workbench
            </Button>
          )}
          <Descriptions column={1} size="small" style={{ marginTop: 16 }}>
            <Descriptions.Item label="Node ID">{selectedNode.id}</Descriptions.Item>
            <Descriptions.Item label="Paper">{selectedNode.paper_title ?? selectedNode.paper_id ?? "—"}</Descriptions.Item>
            <Descriptions.Item label="Entity type">{selectedNode.entity_type ?? "—"}</Descriptions.Item>
            <Descriptions.Item label="Mention">{selectedNode.mention_text ?? "—"}</Descriptions.Item>
          </Descriptions>
          <Divider orientation="left">Connected relations ({connectedEdges.length})</Divider>
          {connectedEdges.length === 0 ? <Text type="secondary">No loaded relations</Text> : (
            <Space direction="vertical" style={{ width: "100%" }}>
              {connectedEdges.slice(0, 12).map((edge) => (
                <Space key={edge.id} wrap>
                  <Tag color={RELATION_COLORS[edge.relation_type] ?? "default"}>{edge.relation_type}</Tag>
                  <Text type="secondary">{edge.source === selectedNode.id ? "→" : "←"}</Text>
                  <Text>{edge.source === selectedNode.id ? edge.target : edge.source}</Text>
                  <Text type="secondary">{Math.round(edge.confidence * 100)}%</Text>
                </Space>
              ))}
            </Space>
          )}
          <Divider orientation="left">Structured content</Divider>
          <Paragraph><pre style={{ whiteSpace: "pre-wrap", background: "#f7f8fa", padding: 12, borderRadius: 6 }}>{JSON.stringify(selectedNode.content, null, 2)}</pre></Paragraph>
        </>}
      </Drawer>
    </Card>
  );
}
