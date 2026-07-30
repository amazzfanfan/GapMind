import { useState, type ReactNode } from "react";
import { Alert, App, Button, Card, Divider, Drawer, Empty, List, Spin, Tag, Typography } from "antd";
import { BulbOutlined } from "@ant-design/icons";
import { discoverApi, claimText } from "../api/discover";
import type { KnowledgeItem } from "../api/types/knowledge";
import type { DiscoverResponse } from "../api/discover";

const { Paragraph, Text, Title } = Typography;

export default function DiscoverOpportunity({ workspaceId, item }: { workspaceId: string; item: KnowledgeItem }) {
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<DiscoverResponse | null>(null);

  const discover = async () => {
    setOpen(true);
    setLoading(true);
    try {
      setResult(await discoverApi.createOpportunity(workspaceId, { claim_item_id: item.id, top_k: 5 }));
    } catch (error) {
      message.error(`Discover Agent failed: ${(error as Error).message}`);
    } finally {
      setLoading(false);
    }
  };

  return <>
    <Button type="primary" icon={<BulbOutlined />} onClick={() => void discover()}>Discover opportunity</Button>
    <Drawer title="Research Opportunity" open={open} width={680} onClose={() => setOpen(false)}>
      {loading ? <div style={{ textAlign: "center", padding: 48 }}><Spin /></div> : !result ? <Empty description="No opportunity generated" /> : <>
        <Title level={4}>{result.opportunity.title}</Title>
        <SpaceRow label="Confidence"><Tag color="blue">{Math.round(result.opportunity.confidence * 100)}%</Tag><Tag>{result.opportunity.status}</Tag></SpaceRow>
        <Divider orientation="left">Claim</Divider>
        <Paragraph>{result.claim_text || claimText(item)}</Paragraph>
        <Divider orientation="left">Summary</Divider>
        <Paragraph>{result.opportunity.summary}</Paragraph>
        <Divider orientation="left">Rationale</Divider>
        <Paragraph>{result.opportunity.rationale}</Paragraph>
        <Divider orientation="left">Suggested directions</Divider>
        <List size="small" dataSource={result.opportunity.suggested_directions} locale={{ emptyText: "No suggested directions" }} renderItem={(direction) => <List.Item>{direction}</List.Item>} />
        <Divider orientation="left">Evidence used</Divider>
        <Alert type={result.counter_evidence.status === "failed" ? "warning" : "info"} showIcon message={`Similar work: ${result.similar_work.total} · Counter evidence: ${result.counter_evidence.total}`} />
        <Card size="small" title="Counter evidence" style={{ marginTop: 12 }}>
          <List size="small" dataSource={result.counter_evidence.items} locale={{ emptyText: "No counter evidence returned" }} renderItem={(evidence) => <List.Item><div><Text strong>{evidence.judgement}</Text> · {evidence.paper_title ?? "workspace paper"}<Paragraph ellipsis={{ rows: 3 }} style={{ margin: 4 }}>{evidence.text}</Paragraph></div></List.Item>} />
        </Card>
        <Card size="small" title="Similar work" style={{ marginTop: 12 }}>
          <List size="small" dataSource={result.similar_work.items} locale={{ emptyText: "No similar work returned" }} renderItem={(evidence) => <List.Item><div><Text strong>{evidence.paper_title ?? "workspace paper"}</Text><Paragraph ellipsis={{ rows: 3 }} style={{ margin: 4 }}>{evidence.text}</Paragraph></div></List.Item>} />
        </Card>
      </>}
    </Drawer>
  </>;
}

function SpaceRow({ label, children }: { label: string; children: ReactNode }) {
  return <div style={{ display: "flex", alignItems: "center", gap: 8 }}><Text type="secondary">{label}</Text>{children}</div>;
}
