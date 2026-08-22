import type { Task } from "../api/types/domain";

/**
 * A failed task remains in the audit trail forever, but the overview should
 * only interrupt the researcher for failures that still need timely action.
 */
export const RECENT_FAILED_TASK_WINDOW_MS = 24 * 60 * 60 * 1000;

export function isTaskNeedingAttention(
  task: Pick<Task, "status" | "created_at" | "updated_at">,
  now = Date.now(),
): boolean {
  if (["queued", "running", "waiting_for_user"].includes(task.status)) {
    return true;
  }
  if (task.status !== "failed") return false;

  const updatedAt = Date.parse(task.updated_at || task.created_at);
  // A malformed timestamp should fail safe: keep the failure visible until it
  // can be inspected instead of silently hiding an unknown recent issue.
  return Number.isNaN(updatedAt) || now - updatedAt <= RECENT_FAILED_TASK_WINDOW_MS;
}
