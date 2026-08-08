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

export type DiscoverStage = (typeof DISCOVER_STAGES)[number];

export const DISCOVER_STAGE_LABELS: Record<DiscoverStage, string> = {
  preflight: "输入检查",
  workspace_retrieval: "工作区检索",
  similar_work: "相似工作",
  counter_evidence: "反证检索",
  external_search: "外部检索",
  external_selection: "外部论文选择",
  fulltext_verification: "全文核验",
  synthesis: "候选综合",
  saved: "保存结果",
};

export function stageSummaryStatus(
  stageSummaries: Record<string, unknown> | null | undefined,
  stage: DiscoverStage,
): string | null {
  const raw = stageSummaries?.[stage];
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const status = (raw as { status?: unknown }).status;
  return typeof status === "string" ? status : null;
}

export function stageSummaryMessage(
  stageSummaries: Record<string, unknown> | null | undefined,
  stage: DiscoverStage,
): string | null {
  const raw = stageSummaries?.[stage];
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const summary = raw as {
    status?: unknown;
    error?: unknown;
    successful_query_count?: unknown;
    failed_query_count?: unknown;
    query_failures?: unknown;
  };
  const status = typeof summary.status === "string" ? summary.status : null;
  if (status === "failed") {
    return typeof summary.error === "string" ? summary.error : "该阶段执行失败";
  }
  if (status === "succeeded_partial") {
    const failures = Array.isArray(summary.query_failures) ? summary.query_failures : [];
    const rateLimited = failures.filter((item) => item && typeof item === "object" && (item as { status_code?: unknown }).status_code === 429).length;
    const reason = rateLimited > 0 ? `；其中 ${rateLimited} 个因 Semantic Scholar 请求频率受限（HTTP 429）失败` : "";
    return `部分成功：${Number(summary.successful_query_count ?? 0)} 个查询成功，${Number(summary.failed_query_count ?? 0)} 个失败，已保留成功结果${reason}`;
  }
  if (status === "succeeded_empty") return "检索已执行，但没有返回候选论文";
  if (status === "skipped") return "该阶段已由用户跳过";
  return null;
}

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

export function currentRunStatus(
  runDetail: { id: string; status: string } | null,
  selectedRun: { id: string; status: string } | null,
): string | null {
  if (runDetail && selectedRun && runDetail.id === selectedRun.id) return runDetail.status;
  return selectedRun?.status ?? null;
}

export function currentRunStage(
  runDetail: { id: string; stage: string } | null,
  selectedRun: { id: string; stage: string } | null,
): string | null {
  if (runDetail && selectedRun && runDetail.id === selectedRun.id) return runDetail.stage;
  return selectedRun?.stage ?? null;
}

export function selectedOpportunityCount(
  opportunities: Array<{ discover_run_id?: string | null }>,
  runId: string | null,
): number {
  return runId ? opportunities.filter((item) => item.discover_run_id === runId).length : opportunities.length;
}
