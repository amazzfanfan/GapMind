export type KnowledgeType =
  | "paper"
  | "method"
  | "task"
  | "dataset"
  | "claim"
  | "evidence"
  | "limitation";

export type KnowledgeStatus =
  | "raw_source"
  | "extracted_candidate"
  | "evidence_backed_proposal"
  | "human_confirmed"
  | "experiment_validated"
  | "deprecated"
  | "rejected"
  | "invalidated";

export interface KnowledgeItem {
  id: string;
  workspace_id: string;
  paper_id: string | null;
  canonical_entity_id: string | null;
  extraction_run_id: string | null;
  item_key: string | null;
  type: KnowledgeType;
  canonical_name: string;
  content: Record<string, unknown>;
  source_provenance: Record<string, unknown>;
  created_by: "user" | "agent" | "system";
  confidence: number;
  status: KnowledgeStatus;
  version: number;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  is_deleted: boolean;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeItemListResponse {
  items: KnowledgeItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface KnowledgeRelation {
  id: string;
  workspace_id: string;
  source_id: string;
  target_id: string;
  relation_type: string;
  confidence: number;
  payload: Record<string, unknown>;
  is_deleted: boolean;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeRelationListResponse {
  items: KnowledgeRelation[];
  total: number;
  limit: number;
  offset: number;
}

export interface EvidenceSpan {
  id: string;
  workspace_id: string;
  knowledge_item_id: string;
  paper_id: string;
  artifact_id: string | null;
  artifact_kind: string | null;
  artifact_version: string | null;
  chunk_index: number | null;
  start_char: number | null;
  end_char: number | null;
  text: string | null;
  relation: string;
  confidence: number;
  created_at: string;
  updated_at: string;
}

export interface EvidenceSpanListResponse {
  items: EvidenceSpan[];
  total: number;
}

export interface KnowledgeGraphNode {
  id: string;
  label: string;
  type: KnowledgeType | string;
  workspace_id: string;
  paper_id: string | null;
  canonical_entity_id: string | null;
  confidence: number;
  status: string;
  content: Record<string, unknown>;
  node_kind: "knowledge" | "paper" | "canonical_entity" | "paper_mention" | string;
  paper_title: string | null;
  entity_type: string | null;
  mention_text: string | null;
  knowledge_item_id: string | null;
}

export interface KnowledgeGraphEdge {
  id: string;
  source: string;
  target: string;
  relation_type: string;
  confidence: number;
  payload: Record<string, unknown>;
}

export interface KnowledgeGraphResponse {
  workspace_id: string;
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
  total_nodes: number;
  total_edges: number;
  truncated: boolean;
  limit: number;
  offset: number;
}

export interface EvidenceContext {
  workspace_id: string;
  paper_id: string;
  artifact_id: string;
  artifact_kind: string;
  filename: string | null;
  content: string;
  spans: EvidenceSpan[];
}

export interface PaperMention {
  id: string;
  workspace_id: string;
  paper_id: string;
  canonical_entity_id: string;
  knowledge_item_id: string | null;
  mention_text: string;
  artifact_id: string | null;
  start_char: number | null;
  end_char: number | null;
  confidence: number;
  status: string;
  created_at: string;
  updated_at: string;
}
