export const DISCOVER_STAGES = [
  "preflight",
  "workspace_retrieval",
  "similar_work",
  "counter_evidence",
  "external_search",
  "external_selection",
  "fulltext_verification",
  "synthesis",
  "saved",
] as const;

export const TERMINAL_RUN_STATUSES = new Set(["succeeded", "failed", "cancelled"]);

export function stageIndex(stage: string | null | undefined): number {
  const index = DISCOVER_STAGES.indexOf(stage as (typeof DISCOVER_STAGES)[number]);
  return index;
}

export function pollingInterval(status: string | null | undefined): number | null {
  if (!status || TERMINAL_RUN_STATUSES.has(status)) return null;
  if (status === "waiting_for_user" || status === "waiting_for_fulltext") return 5000;
  return 2000;
}

export function selectedOpportunityCount(
  opportunities: Array<{ discover_run_id?: string | null }>,
  runId: string | null,
): number {
  return runId ? opportunities.filter((item) => item.discover_run_id === runId).length : opportunities.length;
}
