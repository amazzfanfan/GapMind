import { Collapse, Space, Tag, Typography } from "antd";
import type { ChatMessageSource } from "../../api/chat";

const colors: Record<ChatMessageSource["source_type"], string> = {
  plan: "gold",
  paper: "blue",
  report: "purple",
  code_draft: "orange",
};

export default function ChatSources({ sources }: { sources: ChatMessageSource[] }) {
  if (!sources.length) return null;
  return <Collapse
    className="gm-chat-sources"
    size="small"
    defaultActiveKey={["sources"]}
    items={[{
      key: "sources",
      label: <Typography.Text strong>本次回答使用的来源（{sources.length}）</Typography.Text>,
      children: <Space wrap size={[6, 6]}>
        {sources.map((source) => <Tag key={`${source.marker}-${source.source_id}`} color={colors[source.source_type]}>
          <strong>[{source.marker}]</strong> {source.label}：{source.title}
          {source.source_type === "code_draft" ? "（未运行验证）" : ""}
        </Tag>)}
      </Space>,
    }]}
  />;
}
