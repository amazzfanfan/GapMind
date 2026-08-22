import { describe, expect, it } from "vitest";
import {
  aggregateDashboardRecommendations,
  dashboardRecommendationEntries,
} from "./dashboardRecommendationState";
import type { PaperRecommendation, PaperRecommendationResponse } from "../api/recommendations";
import type { Workspace } from "../api/types/workspace";

const workspace = (id: string) => ({ id, name: id } as Workspace);
const response = (paperId: string): PaperRecommendationResponse => ({
  workspace_id: "ignored",
  profile_topics: ["GNN"],
  has_profile: true,
  generated_at: "2026-08-22T00:00:00Z",
  stale: true,
  items: [{
    id: paperId,
    workspace_id: "ignored",
    external_paper_id: paperId,
    paper: { paperId, title: paperId, authors: [] } as unknown as PaperRecommendation["paper"],
    score: 0.8,
    reasons: [],
    topics: [],
    status: "suggested",
    generated_at: "2026-08-22T00:00:00Z",
  }],
});

describe("dashboard recommendation aggregation", () => {
  it("shows cached sources without waiting for cold sources", () => {
    const cold = workspace("cold");
    const cached = workspace("cached");
    const entries = new Map([
      [cached.id, dashboardRecommendationEntries(cached, response("paper-1"))],
    ]);

    expect(aggregateDashboardRecommendations([cold, cached], entries)).toEqual([
      expect.objectContaining({ workspace: cached, item: expect.objectContaining({ external_paper_id: "paper-1" }) }),
    ]);
  });
});
