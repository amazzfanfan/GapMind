import { useMemo } from "react";
import { Button, Dropdown, Empty, Input, List, Spin, Typography } from "antd";
import { DeleteOutlined, EditOutlined, EllipsisOutlined, PlusOutlined, SearchOutlined } from "@ant-design/icons";
import type { ChatConversation } from "../../api/chat";
import { groupConversations, truncateChatTitle } from "../../state/chatState";

interface Props {
  items: ChatConversation[];
  selectedId?: string;
  loading: boolean;
  query: string;
  onQueryChange: (value: string) => void;
  onNew: () => void;
  onSelect: (id: string) => void;
  onRename: (conversation: ChatConversation) => void;
  onDelete: (conversation: ChatConversation) => void;
}

export default function ChatHistory({ items, selectedId, loading, query, onQueryChange, onNew, onSelect, onRename, onDelete }: Props) {
  const groups = useMemo(() => groupConversations(items), [items]);
  return (
    <div className="gm-chat-history">
      <Button type="primary" block icon={<PlusOutlined />} onClick={onNew}>新建对话</Button>
      <Input allowClear value={query} prefix={<SearchOutlined />} placeholder="搜索历史对话" aria-label="搜索历史对话" onChange={(event) => onQueryChange(event.target.value)} style={{ margin: "14px 0" }} />
      {loading ? <div className="gm-chat-history-loading"><Spin size="small" /></div> : groups.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无历史对话" /> : groups.map((group) => (
        <section key={group.label} className="gm-chat-history-group">
          <Typography.Text type="secondary" className="gm-chat-history-label">{group.label}</Typography.Text>
          <List
            split={false}
            dataSource={group.items}
            renderItem={(conversation) => (
              <List.Item
                className={`gm-chat-history-item ${selectedId === conversation.id ? "is-selected" : ""}`}
                onClick={() => onSelect(conversation.id)}
                actions={[<ConversationActions key="actions" conversation={conversation} onRename={onRename} onDelete={onDelete} />]}
              >
                <Typography.Text ellipsis={{ tooltip: conversation.title }}>{truncateChatTitle(conversation.title)}</Typography.Text>
              </List.Item>
            )}
          />
        </section>
      ))}
    </div>
  );
}

function ConversationActions({ conversation, onRename, onDelete }: { conversation: ChatConversation; onRename: (conversation: ChatConversation) => void; onDelete: (conversation: ChatConversation) => void }) {
  return (
    <Dropdown
      trigger={["click"]}
      menu={{
        items: [
          { key: "rename", icon: <EditOutlined />, label: "重命名" },
          { key: "delete", danger: true, icon: <DeleteOutlined />, label: "删除" },
        ],
        onClick: ({ key }) => key === "rename" ? onRename(conversation) : onDelete(conversation),
      }}
    >
      <Button type="text" size="small" aria-label={`操作：${conversation.title}`} icon={<EllipsisOutlined />} onClick={(event) => event.stopPropagation()} />
    </Dropdown>
  );
}
