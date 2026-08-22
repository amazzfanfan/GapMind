import { Button, Select, Space, Tag, Typography } from "antd";
import { DatabaseOutlined, MenuOutlined } from "@ant-design/icons";
import type { Workspace } from "../../api/types/workspace";
import { INDEPENDENT_WORKSPACE_NAME } from "../../state/independentMode";

interface Props {
  title: string;
  workspaces: Workspace[];
  workspaceId?: string;
  independent?: boolean;
  scopeLocked: boolean;
  onWorkspaceChange: (workspaceId?: string) => void;
  onOpenHistory: () => void;
}

export default function ChatHeader({ title, workspaces, workspaceId, independent = false, scopeLocked, onWorkspaceChange, onOpenHistory }: Props) {
  const selectableWorkspaces = workspaces.filter(
    (workspace) => workspace.name !== INDEPENDENT_WORKSPACE_NAME,
  );
  return <div className="gm-chat-header">
    <div className="gm-chat-header-title"><Button className="gm-chat-mobile-history" type="text" icon={<MenuOutlined />} aria-label="打开历史对话" onClick={onOpenHistory} /><Typography.Title level={4} ellipsis={{ tooltip: title }}>{title}</Typography.Title></div>
    <Space size={8}>
      {scopeLocked && <Tag color={independent ? "cyan" : workspaceId ? "blue" : "default"}>{independent ? "独立模式（不检索）" : workspaceId ? "工作区 RAG" : "普通对话"}</Tag>}
      <Select
        className="gm-chat-workspace-select"
        value={independent ? "independent" : workspaceId ?? "general"}
        disabled={scopeLocked}
        suffixIcon={<DatabaseOutlined />}
        aria-label="选择对话工作区"
        onChange={(value) => onWorkspaceChange(value === "general" ? undefined : value)}
        options={[
          { value: "general", label: "普通对话（不检索）" },
          ...(independent ? [{ value: "independent", label: "独立模式（不检索）" }] : []),
          ...selectableWorkspaces.map((workspace) => ({ value: workspace.id, label: workspace.name })),
        ]}
      />
    </Space>
  </div>;
}
