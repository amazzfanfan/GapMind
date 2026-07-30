import { describe, expect, it } from "vitest";
import { currentRunStage, currentRunStatus, DISCOVER_STAGES, pollingInterval, selectedOpportunityCount, stageIndex } from "./discoverState";

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

  it("does not read status before either run object has loaded", () => {
    expect(currentRunStatus(null, null)).toBeNull();
    expect(currentRunStatus(null, { id: "run-1", status: "queued" })).toBe("queued");
    expect(currentRunStatus({ id: "run-1", status: "running" }, { id: "run-1", status: "queued" })).toBe("running");
  });

  it("does not read stage before either run object has loaded", () => {
    expect(currentRunStage(null, null)).toBeNull();
    expect(currentRunStage(null, { id: "run-1", stage: "preflight" })).toBe("preflight");
    expect(currentRunStage({ id: "run-1", stage: "synthesis" }, { id: "run-1", stage: "preflight" })).toBe("synthesis");
  });

  it("counts opportunities only for the selected run", () => {
    const items = [{ discover_run_id: "run-a" }, { discover_run_id: "run-a" }, { discover_run_id: "run-b" }];
    expect(selectedOpportunityCount(items, "run-a")).toBe(2);
    expect(selectedOpportunityCount(items, null)).toBe(3);
  });
});
