import { Button, Select, Space, Tag, Typography } from "antd";
import { DatabaseOutlined, MenuOutlined } from "@ant-design/icons";
import type { Workspace } from "../../api/types/workspace";

interface Props {
  title: string;
  workspaces: Workspace[];
  workspaceId?: string;
  scopeLocked: boolean;
  onWorkspaceChange: (workspaceId?: string) => void;
  onOpenHistory: () => void;
}

export default function ChatHeader({ title, workspaces, workspaceId, scopeLocked, onWorkspaceChange, onOpenHistory }: Props) {
  return <div className="gm-chat-header">
    <div className="gm-chat-header-title"><Button className="gm-chat-mobile-history" type="text" icon={<MenuOutlined />} aria-label="打开历史对话" onClick={onOpenHistory} /><Typography.Title level={4} ellipsis={{ tooltip: title }}>{title}</Typography.Title></div>
    <Space size={8}>
      {scopeLocked && <Tag color={workspaceId ? "blue" : "default"}>{workspaceId ? "工作区 RAG" : "普通对话"}</Tag>}
      <Select
        className="gm-chat-workspace-select"
        value={workspaceId ?? "general"}
        disabled={scopeLocked}
        suffixIcon={<DatabaseOutlined />}
        aria-label="选择对话工作区"
        onChange={(value) => onWorkspaceChange(value === "general" ? undefined : value)}
        options={[
          { value: "general", label: "普通对话（不检索）" },
          ...workspaces.map((workspace) => ({ value: workspace.id, label: workspace.name })),
        ]}
      />
    </Space>
  </div>;
}
