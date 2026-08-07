import apiClient from "./client";
import type { KnowledgeItem } from "./types/knowledge";

export interface RetrievalResultItem {
  result_id: string;
  source_scope: string;
  evidence_level: string;
  paper_id: string | null;
  external_paper_id?: string | null;
  paper_title: string | null;
  chunk_id?: string | null;
  artifact_id?: string | null;
  section?: string | null;
  text: string;
  score: number;
  judgement: string;
  judgement_confidence: number;
  retrieval_stage: string;
}

export interface RetrievalResponse {
  workspace_id: string;
  query: string;
  purpose: string;
  status: string;
  items: RetrievalResultItem[];
  total: number;
  filters_applied?: Record<string, unknown>;
  error: string | null;
}

export interface ResearchOpportunity {
  id: string;
  workspace_id: string;
  claim_item_id: string | null;
  discover_run_id?: string | null;
  current_version_id?: string | null;
  title: string;
  summary: string;
  rationale: string;
  suggested_directions: string[];
  confidence: number;
  status: string;
  source_payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DiscoverExternalCandidate {
  id: string;
  discover_run_id: string;
  query: string;
  rank: number;
  external_paper_id: string;
  title: string;
  authors: string[];
  year: number | null;
  abstract: string | null;
  open_access_pdf: Record<string, unknown> | null;
  role: string;
  role_confidence: number;
  evidence_level: string;
  verification_status: string;
  imported_paper_id: string | null;
  snapshot_payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DiscoverRun {
  id: string;
  workspace_id: string;
  task_id: string | null;
  parent_run_id: string | null;
  trigger_type: string;
  input_topic: string | null;
  input_claim_item_id: string | null;
  input_payload: Record<string, unknown>;
  scope: Record<string, unknown>;
  config: Record<string, unknown>;
  status: string;
  stage: string;
  progress: number;
  verification_status: string;
  stage_summaries: Record<string, unknown>;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface DiscoverRunDetail extends DiscoverRun {
  external_candidates: DiscoverExternalCandidate[];
  opportunities: ResearchOpportunity[];
}

export interface OpportunityVersion {
  id: string;
  opportunity_id: string;
  version_number: number;
  title: string;
  problem_statement: string;
  research_scope: string;
  why_existing_work_is_insufficient: string;
  candidate_research_question: string;
  candidate_hypothesis: string;
  candidate_validation_plan: Record<string, unknown>;
  open_risks: string[];
  novelty_score: number;
  feasibility_score: number;
  significance_score: number;
  confidence: number;
  evidence_coverage: number;
  verification_status: string;
  synthesis_metadata: Record<string, unknown>;
  created_by: string;
  created_at: string;
}

export interface OpportunityEvidence {
  id: string;
  opportunity_version_id: string;
  relation: string;
  source_scope: string;
  evidence_level: string;
  paper_id: string | null;
  external_candidate_id: string | null;
  evidence_span_id: string | null;
  artifact_id: string | null;
  chunk_id: string | null;
  rank: number | null;
  score: number;
  judgement: string;
  judgement_confidence: number;
  display_excerpt: string;
  snapshot_payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface OpportunityEvidenceContext {
  evidence: OpportunityEvidence;
  available: boolean;
  paper_id: string | null;
  artifact_id: string | null;
  artifact_kind: string | null;
  filename: string | null;
  content: string | null;
  start_char: number | null;
  end_char: number | null;
  message: string | null;
}

export interface HumanDecision {
  id: string;
  opportunity_id: string;
  from_version_id: string;
  to_version_id: string;
  action: string;
  reason: string | null;
  defer_condition: string | null;
  actor: string;
  created_at: string;
}

export interface ResearchPlan {
  id: string;
  workspace_id: string;
  opportunity_id: string;
  opportunity_version_id: string;
  status: string;
  research_question: string;
  hypothesis: string;
  scope_and_assumptions: string;
  datasets: string[];
  baselines: string[];
  metrics: string[];
  validation_steps: string[];
  expected_supporting_result: string;
  falsification_criteria: string;
  risks: string[];
  resource_constraints: string;
  created_at: string;
  updated_at: string;
}

export interface OpportunityDetail {
  opportunity: ResearchOpportunity;
  current_version: OpportunityVersion | null;
  versions: OpportunityVersion[];
  evidence: OpportunityEvidence[];
  decisions: HumanDecision[];
  plan: ResearchPlan | null;
}

export const discoverApi = {
  async createRun(workspaceId: string, payload: {
    input: { topic?: string; claim_item_id?: string; paper_ids?: string[]; keywords?: string[]; constraints?: string };
    scope?: { year_from?: number; year_to?: number; open_access_preferred?: boolean };
    config?: { max_opportunities?: number; top_k?: number; include_counter_evidence?: boolean; use_reranker?: boolean; use_judge?: boolean };
  }): Promise<{ run_id: string; task_id: string | null; status: string }> {
    return (await apiClient.post(`/workspaces/${workspaceId}/discover/runs`, payload)).data;
  },
  async listRuns(workspaceId: string): Promise<{ items: DiscoverRun[]; total: number }> {
    return (await apiClient.get(`/workspaces/${workspaceId}/discover/runs`, { params: { limit: 50 } })).data;
  },
  async getRun(workspaceId: string, runId: string): Promise<DiscoverRunDetail> {
    return (await apiClient.get(`/workspaces/${workspaceId}/discover/runs/${runId}`)).data;
  },
  async selectExternal(workspaceId: string, runId: string, candidateIds: string[]): Promise<DiscoverRun> {
    return (await apiClient.post(`/workspaces/${workspaceId}/discover/runs/${runId}/external-selection`, { candidate_ids: candidateIds, action: "import_and_verify" })).data;
  },
  async cancelRun(workspaceId: string, runId: string): Promise<DiscoverRun> {
    return (await apiClient.post(`/workspaces/${workspaceId}/discover/runs/${runId}/cancel`)).data;
  },
  async deleteRun(workspaceId: string, runId: string): Promise<void> {
    await apiClient.delete(`/workspaces/${workspaceId}/discover/runs/${runId}`);
  },
  async listOpportunities(workspaceId: string, options: { status?: string; runId?: string; pendingOnly?: boolean; limit?: number; offset?: number } = {}): Promise<{ items: ResearchOpportunity[]; total: number; limit: number; offset: number }> {
    return (await apiClient.get(`/workspaces/${workspaceId}/discover/opportunities`, {
      params: {
        status: options.status,
        run_id: options.runId,
        pending_only: options.pendingOnly,
        limit: options.limit ?? 50,
        offset: options.offset ?? 0,
      },
    })).data;
  },
  async getOpportunity(workspaceId: string, opportunityId: string): Promise<OpportunityDetail> {
    return (await apiClient.get(`/workspaces/${workspaceId}/discover/opportunities/${opportunityId}`)).data;
  },
  async getEvidenceContext(workspaceId: string, evidenceId: string): Promise<OpportunityEvidenceContext> {
    return (await apiClient.get(`/workspaces/${workspaceId}/discover/evidence/${evidenceId}/context`)).data;
  },
  async confirm(workspaceId: string, opportunityId: string, versionId?: string, note?: string): Promise<ResearchOpportunity> {
    return (await apiClient.post(`/workspaces/${workspaceId}/discover/opportunities/${opportunityId}/confirm`, { version_id: versionId, note })).data;
  },
  async editConfirm(workspaceId: string, opportunityId: string, payload: { base_version_id: string; changes: Record<string, unknown>; note?: string }): Promise<ResearchOpportunity> {
    return (await apiClient.patch(`/workspaces/${workspaceId}/discover/opportunities/${opportunityId}`, payload)).data;
  },
  async reject(workspaceId: string, opportunityId: string, note?: string): Promise<ResearchOpportunity> {
    return (await apiClient.post(`/workspaces/${workspaceId}/discover/opportunities/${opportunityId}/reject`, { note })).data;
  },
  async defer(workspaceId: string, opportunityId: string, note?: string, defer_condition?: string): Promise<ResearchOpportunity> {
    return (await apiClient.post(`/workspaces/${workspaceId}/discover/opportunities/${opportunityId}/defer`, { note, defer_condition })).data;
  },
  async convert(workspaceId: string, opportunityId: string): Promise<{ plan: ResearchPlan }> {
    return (await apiClient.post(`/workspaces/${workspaceId}/discover/opportunities/${opportunityId}/convert`)).data;
  },
};

export function claimText(item: KnowledgeItem): string {
  const statement = item.content?.statement;
  return typeof statement === "string" && statement.trim() ? statement : item.canonical_name;
}
