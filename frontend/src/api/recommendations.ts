import apiClient from "./client";
import type { SemanticScholarPaper } from "./semanticScholar";

export type RecommendationFeedbackAction =
  | "open"
  | "favorite"
  | "imported"
  | "reading"
  | "dismiss"
  | "restore";

export interface PaperRecommendation {
  id: string;
  workspace_id: string;
  external_paper_id: string;
  paper: SemanticScholarPaper;
  score: number;
  reasons: string[];
  topics: string[];
  status: string;
  generated_at: string;
}

export interface PaperRecommendationResponse {
  workspace_id: string;
  profile_topics: string[];
  has_profile: boolean;
  generated_at: string | null;
  stale: boolean;
  items: PaperRecommendation[];
}

export const recommendationsApi = {
  async list(workspaceId: string): Promise<PaperRecommendationResponse> {
    const { data } = await apiClient.get<PaperRecommendationResponse>(
      `/workspaces/${encodeURIComponent(workspaceId)}/recommendations`,
    );
    return data;
  },

  async refresh(workspaceId: string): Promise<PaperRecommendationResponse> {
    const { data } = await apiClient.post<PaperRecommendationResponse>(
      `/workspaces/${encodeURIComponent(workspaceId)}/recommendations/refresh`,
    );
    return data;
  },

  async feedback(
    workspaceId: string,
    externalPaperId: string,
    action: RecommendationFeedbackAction,
  ): Promise<PaperRecommendation> {
    const { data } = await apiClient.post<PaperRecommendation>(
      `/workspaces/${encodeURIComponent(workspaceId)}/recommendations/${encodeURIComponent(externalPaperId)}/feedback`,
      { action },
    );
    return data;
  },
};

export default recommendationsApi;

