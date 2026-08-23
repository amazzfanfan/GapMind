import { describe, expect, it } from "vitest";
import { gapAnnotationProvenanceLabel, isRemoteGapFallback } from "./gapAnnotation";

describe("gap annotation provenance", () => {
  it("labels valid remote results as candidates rather than local evidence", () => {
    const annotation = { model_provider: "remote", status: "valid" };

    expect(isRemoteGapFallback(annotation)).toBe(true);
    expect(gapAnnotationProvenanceLabel(annotation)).toBe("远程降级候选");
  });

  it("does not label invalid or local annotations as remote candidates", () => {
    expect(isRemoteGapFallback({ model_provider: "remote", status: "invalid" })).toBe(false);
    expect(gapAnnotationProvenanceLabel({ model_provider: "ollama", status: "valid" })).toBe("本地标注");
    expect(gapAnnotationProvenanceLabel({ model_provider: "ollama", status: "invalid" })).toBe("本地标注无效");
  });
});
