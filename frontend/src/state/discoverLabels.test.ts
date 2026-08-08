import { describe, expect, it } from "vitest";
import {
  discoverStageLabel,
  evidenceLevelDisplayLabel,
  evidenceRelationLabel,
  evidenceSourceScopeLabel,
  gateMessageLabel,
  localizedGeneratedText,
  opportunityStatusLabel,
  verificationStatusLabel,
} from "./discoverLabels";

describe("Discover 中文界面标签", () => {
  it("translates workflow, opportunity, verification, and evidence metadata", () => {
    expect(discoverStageLabel("counter_evidence")).toBe("反证检索");
    expect(opportunityStatusLabel("needs_more_evidence")).toBe("需要更多证据");
    expect(verificationStatusLabel("verification_incomplete")).toBe("核验不完整");
    expect(evidenceRelationLabel("supports")).toBe("支持证据");
    expect(evidenceSourceScopeLabel("external_fulltext")).toBe("外部论文全文");
    expect(evidenceLevelDisplayLabel("full_text")).toBe("全文证据");
  });

  it("localizes legacy fallback prose without changing unknown source text", () => {
    expect(localizedGeneratedText("Investigate the boundary conditions of the claim"))
      .toBe("研究该论断成立与失效的边界条件");
    expect(localizedGeneratedText("An evidence excerpt from the paper."))
      .toBe("An evidence excerpt from the paper.");
    expect(gateMessageLabel("requires two independent full-text supporting papers"))
      .toContain("两篇");
  });
});
