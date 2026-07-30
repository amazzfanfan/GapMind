import { describe, expect, it } from "vitest";
import { DISCOVER_STAGES, pollingInterval, selectedOpportunityCount, stageIndex } from "./discoverState";

describe("Discover state helpers", () => {
  it("keeps the complete stage order and unknown stages visible", () => {
    expect(DISCOVER_STAGES).toContain("fulltext_verification");
    expect(DISCOVER_STAGES).toContain("saved");
    expect(stageIndex("fulltext_verification")).toBe(6);
    expect(stageIndex("unexpected_stage")).toBe(-1);
  });

  it("uses low-frequency polling for waiting states and stops at terminal states", () => {
    expect(pollingInterval("running")).toBe(2000);
    expect(pollingInterval("waiting_for_fulltext")).toBe(5000);
    expect(pollingInterval("succeeded")).toBeNull();
    expect(pollingInterval("cancelled")).toBeNull();
  });

  it("counts opportunities only for the selected run", () => {
    const items = [{ discover_run_id: "run-a" }, { discover_run_id: "run-a" }, { discover_run_id: "run-b" }];
    expect(selectedOpportunityCount(items, "run-a")).toBe(2);
    expect(selectedOpportunityCount(items, null)).toBe(3);
  });
});
