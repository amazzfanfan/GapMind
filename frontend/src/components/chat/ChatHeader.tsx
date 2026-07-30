import { Button, Space, Typography } from "antd";
import { MenuOutlined } from "@ant-design/icons";

export default function ChatHeader({ title, onOpenHistory }: { title: string; onOpenHistory: () => void }) {
  return <div className="gm-chat-header"><Button className="gm-chat-mobile-history" type="text" icon={<MenuOutlined />} aria-label="打开历史对话" onClick={onOpenHistory} /><Typography.Title level={4} ellipsis={{ tooltip: title }}>{title}</Typography.Title><Space /></div>;
}
