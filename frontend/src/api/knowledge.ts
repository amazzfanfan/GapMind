import apiClient from "./client";
import type { ExtractionRejectionListResponse } from "./types/domain";

export const knowledgeApi = {
  async listExtractionRejections(
    workspaceId: string,
    runId: string,
    params: {
      kind?: string;
      stage?: string;
      reason_code?: string;
      limit?: number;
      offset?: number;
    } = {}
  ): Promise<ExtractionRejectionListResponse> {
    const response = await apiClient.get<ExtractionRejectionListResponse>(
      `/workspaces/${workspaceId}/extraction-runs/${runId}/rejections`,
      { params }
    );
    return response.data;
  },
};

export default knowledgeApi;
