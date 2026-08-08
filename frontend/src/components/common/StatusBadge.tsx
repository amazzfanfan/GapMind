import { Tag } from "antd";

export interface StatusMeta {
  label: string;
  color: string;
}

const STATUS_META: Record<string, StatusMeta> = {
  queued: { label: "排队中", color: "default" },
  running: { label: "正在处理", color: "processing" },
  waiting_for_user: { label: "需要你处理", color: "warning" },
  waiting_for_fulltext: { label: "等待全文准备", color: "warning" },
  succeeded: { label: "已完成", color: "success" },
  failed: { label: "处理失败", color: "error" },
  cancel_requested: { label: "正在取消", color: "default" },
  cancelled: { label: "已取消", color: "default" },
  needs_more_evidence: { label: "证据不足", color: "warning" },
  confirmed: { label: "已确认", color: "success" },
  edited_confirmed: { label: "编辑后确认", color: "success" },
  rejected: { label: "已驳回", color: "error" },
  deferred: { label: "暂缓", color: "warning" },
  not_applicable: { label: "无需处理", color: "default" },
  pending: { label: "待处理", color: "default" },
  parsing: { label: "正在解析", color: "processing" },
  parsed: { label: "已解析", color: "success" },
  extracted: { label: "已提取知识", color: "success" },
  verified: { label: "已验证", color: "success" },
  in_progress: { label: "进行中", color: "processing" },
  imported_pending_parse: { label: "等待解析", color: "warning" },
  verification_failed: { label: "验证失败", color: "error" },
  metadata_only: { label: "仅有元数据", color: "warning" },
  full_text: { label: "有全文证据", color: "success" },
};

export function getStatusMeta(status: string | null | undefined): StatusMeta {
  if (!status) return { label: "未设置", color: "default" };
  return STATUS_META[status] ?? { label: status, color: "default" };
}

export function taskTypeLabel(taskType: string): string {
  const labels: Record<string, string> = {
    parse_pdf: "论文解析",
    extract_knowledge: "知识提取",
    embed_chunks: "全文索引",
    discover_agent: "研究机会发现",
    extract_gap_annotation: "研究空白抽取",
    semantic_scholar_search: "论文检索",
  };
  return labels[taskType] ?? "后台处理";
}

export default function StatusBadge({
  status,
  withRaw = false,
}: {
  status: string | null | undefined;
  withRaw?: boolean;
}) {
  const meta = getStatusMeta(status);
  return (
    <Tag color={meta.color}>
      {meta.label}
      {withRaw && status && status !== meta.label ? ` · ${status}` : ""}
    </Tag>
  );
}
