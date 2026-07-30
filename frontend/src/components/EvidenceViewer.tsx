import { useEffect, useMemo, useState } from "react";
import { Alert, App, Button, Drawer, Empty, Spin, Tag, Typography } from "antd";
import { DownloadOutlined, FileSearchOutlined } from "@ant-design/icons";
import apiClient from "../api/client";
import knowledgeApi from "../api/knowledge";
import type { EvidenceContext, EvidenceSpan } from "../api/types/knowledge";

const { Text } = Typography;

interface Segment {
  text: string;
  highlighted: boolean;
  relation?: string;
}

function buildSegments(content: string, spans: EvidenceSpan[]): Segment[] {
  const valid = spans
    .filter((span) => span.start_char !== null && span.end_char !== null && span.end_char > span.start_char)
    .map((span) => ({ start: Math.max(0, span.start_char ?? 0), end: Math.min(content.length, span.end_char ?? 0), relation: span.relation }))
    .filter((span) => span.end > span.start)
    .sort((a, b) => a.start - b.start);
  if (!valid.length) return [{ text: content, highlighted: false }];
  const boundaries = Array.from(new Set([0, content.length, ...valid.flatMap((span) => [span.start, span.end])])).sort((a, b) => a - b);
  return boundaries.slice(0, -1).map((start, index) => {
    const end = boundaries[index + 1];
    const match = valid.find((span) => start < span.end && end > span.start);
    return { text: content.slice(start, end), highlighted: Boolean(match), relation: match?.relation };
  });
}

export default function EvidenceViewer({
  workspaceId,
  itemId,
  span,
}: {
  workspaceId: string;
  itemId: string;
  span: EvidenceSpan;
}) {
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [context, setContext] = useState<EvidenceContext | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    knowledgeApi
      .evidenceContext(workspaceId, itemId)
      .then(setContext)
      .catch((error) => message.error(`Failed to load source: ${(error as Error).message}`))
      .finally(() => setLoading(false));
  }, [itemId, message, open, workspaceId]);

  const segments = useMemo(
    () => (context ? buildSegments(context.content, context.spans) : []),
    [context],
  );
  const downloadUrl = context
    ? `${apiClient.defaults.baseURL}/workspaces/${workspaceId}/artifacts/${context.artifact_id}/download`
    : "#";

  return <>
    <Button size="small" icon={<FileSearchOutlined />} onClick={() => setOpen(true)}>定位原文</Button>
    <Drawer title="Evidence source" open={open} width="760px" onClose={() => setOpen(false)}>
      {loading ? <div style={{ textAlign: "center", padding: 48 }}><Spin /></div> : !context ? <Empty description="No parsed markdown source" /> : <>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
          <Text type="secondary">{context.filename ?? "parsed_markdown"} · highlighted span {span.start_char ?? "—"}–{span.end_char ?? "—"}</Text>
          <Button icon={<DownloadOutlined />} href={downloadUrl} target="_blank">Download parsed_markdown</Button>
        </div>
        <Alert type="info" showIcon message="证据偏移对应 parsed_markdown 字符位置；黄色区域为当前 Knowledge Item 的证据原文。" style={{ marginBottom: 12 }} />
        <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", lineHeight: 1.75, background: "#fafafa", padding: 16, borderRadius: 8, maxHeight: "70vh", overflow: "auto" }}>
          {segments.map((segment, index) => segment.highlighted ? <mark key={index} style={{ background: segment.relation === "contradicts" ? "#ffccc7" : "#fff566", padding: 0 }} title={segment.relation}>{segment.text}</mark> : <span key={index}>{segment.text}</span>)}
        </pre>
        <Tag color={span.relation === "contradicts" ? "red" : "gold"}>{span.relation}</Tag>
      </>}
    </Drawer>
  </>;
}
