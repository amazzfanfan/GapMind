import { Button } from "antd";
import { BulbOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import type { KnowledgeItem } from "../api/types/knowledge";
import { claimText } from "../api/discover";

export default function DiscoverOpportunity({
  workspaceId,
  item,
}: {
  workspaceId: string;
  item: KnowledgeItem;
}) {
  const navigate = useNavigate();
  const params = new URLSearchParams({
    claim_item_id: item.id,
    claim_text: claimText(item),
  });
  if (item.paper_id) params.set("source_paper_id", item.paper_id);

  return (
    <Button
      type="primary"
      icon={<BulbOutlined />}
      onClick={() => navigate(`/workspaces/${workspaceId}/discover?${params.toString()}`)}
    >
      Use in Discover
    </Button>
  );
}
