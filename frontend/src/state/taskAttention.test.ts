import { describe, expect, it } from "vitest";
import { RECENT_FAILED_TASK_WINDOW_MS, isTaskNeedingAttention } from "./taskAttention";

const now = Date.UTC(2026, 7, 22, 12, 0, 0);
const task = (status: "queued" | "running" | "waiting_for_user" | "succeeded" | "failed", updated_at: string) => ({
  status,
  created_at: updated_at,
  updated_at,
});

describe("isTaskNeedingAttention", () => {
  it("keeps active and recent failures on the overview", () => {
    expect(isTaskNeedingAttention(task("queued", "2026-08-01T00:00:00Z"), now)).toBe(true);
    expect(isTaskNeedingAttention(task("waiting_for_user", "2026-08-01T00:00:00Z"), now)).toBe(true);
    expect(isTaskNeedingAttention(task("failed", "2026-08-22T11:00:00Z"), now)).toBe(true);
  });

  it("keeps old failures in audit without showing them as current work", () => {
    const old = new Date(now - RECENT_FAILED_TASK_WINDOW_MS - 1).toISOString();
    expect(isTaskNeedingAttention(task("failed", old), now)).toBe(false);
    expect(isTaskNeedingAttention(task("succeeded", "2026-08-22T11:00:00Z"), now)).toBe(false);
  });
});
