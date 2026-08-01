import { describe, expect, it } from "vitest";
import { getStatusMeta, taskTypeLabel } from "./StatusBadge";

describe("shared status language", () => {
  it("maps workflow states to user-facing labels", () => {
    expect(getStatusMeta("waiting_for_fulltext").label).toBe("等待全文准备");
    expect(getStatusMeta("needs_more_evidence").label).toBe("证据不足");
    expect(getStatusMeta("unknown_state").label).toBe("unknown_state");
  });

  it("hides internal task names behind research language", () => {
    expect(taskTypeLabel("parse_pdf")).toBe("论文解析");
    expect(taskTypeLabel("discover_agent")).toBe("研究机会发现");
  });
});
