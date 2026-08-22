import { useState } from "react";
import { Button, Dropdown, Input, Select, Space, Tag, Typography } from "antd";
import type { MenuProps } from "antd";
import { CodeOutlined, ExperimentOutlined, FileSearchOutlined, FileTextOutlined, MoreOutlined, SendOutlined } from "@ant-design/icons";
import { shouldSendOnEnter } from "../../state/chatState";

export type ChatMode = "chat" | "research_plan" | "code_generation" | "analyze" | "write" | "respond";

interface Props {
  loading: boolean;
  onSend: (value: string) => void;
  value: string;
  onChange: (value: string) => void;
  workspaceEnabled: boolean;
  mode: ChatMode;
  onModeChange: (mode: ChatMode) => void;
  planOptions: { label: string; value: string; title?: string }[];
  researchPlanId?: string;
  onResearchPlanChange: (value?: string) => void;
  sourceOptions: { label: string; value: string; title?: string }[];
  sourceArtifactIds: string[];
  onSourceArtifactChange: (value: string[]) => void;
}

const modeLabels: Record<ChatMode, string> = {
  chat: "直接提问",
  research_plan: "生成研究计划",
  code_generation: "代码生成",
  analyze: "结果分析",
  write: "论文写作",
  respond: "审稿回复",
};

const modeIcons: Record<Exclude<ChatMode, "chat">, React.ReactNode> = {
  research_plan: <ExperimentOutlined />,
  code_generation: <CodeOutlined />,
  analyze: <FileSearchOutlined />,
  write: <FileTextOutlined />,
  respond: <FileTextOutlined />,
};

export default function ChatComposer({
  loading,
  onSend,
  value,
  onChange,
  workspaceEnabled,
  mode,
  onModeChange,
  planOptions,
  researchPlanId,
  onResearchPlanChange,
  sourceOptions,
  sourceArtifactIds,
  onSourceArtifactChange,
}: Props) {
  const [focused, setFocused] = useState(false);
  const sendDisabled = !value.trim() || loading || (mode === "code_generation" && !researchPlanId);
  const send = () => {
    const content = value.trim();
    if (sendDisabled) return;
    onSend(content);
  };
  const placeholder = mode === "research_plan" ? "描述研究目标、资源约束或希望验证的假设…"
    : mode === "code_generation" ? "描述希望生成的实验代码、框架或运行约束…"
    : mode === "analyze" ? "粘贴实验结果（JSON）或描述实验结论…"
    : mode === "write" ? "描述论文主题、目标章节或写作重点…"
    : mode === "respond" ? "粘贴审稿意见，逐条回应…"
    : "输入问题，不必先选择功能…";
  const hint = mode === "research_plan" ? "这是一次操作建议，确认后才会创建 AgentRun 和研究计划草案。"
    : mode === "code_generation" ? "这是一次操作建议，确认后才会创建 AgentRun；代码只生成候选文件，不会自动执行。"
    : mode === "analyze" ? (workspaceEnabled ? "确认后才会创建结果分析 Agent；可选绑定研究计划。" : "独立模式：确认后分析本次提供的实验材料。")
    : mode === "write" ? (workspaceEnabled ? "确认后才会创建论文写作 Agent；可选绑定研究计划。" : "独立模式：确认后生成论文草稿。")
    : mode === "respond" ? (workspaceEnabled ? "确认后才会创建审稿回复 Agent；可选绑定研究计划。" : "独立模式：确认后生成逐条回复。")
    : "工作区论文是 E 来源；计划、报告和代码草案会以独立来源标注。";
  const operationItems: MenuProps["items"] = (Object.keys(modeLabels) as ChatMode[])
    .filter((item) => item !== "chat")
    .map((item) => ({
      key: item,
      icon: modeIcons[item as Exclude<ChatMode, "chat">],
      label: modeLabels[item],
      disabled: !workspaceEnabled && (item === "research_plan" || item === "code_generation"),
    }));

  return <div className={`gm-chat-composer ${focused ? "is-focused" : ""}`}>
    <div className="gm-chat-agent-toolbar">
      <Space wrap size={[8, 8]}>
        <Tag color={mode === "chat" ? "blue" : "gold"}>{mode === "chat" ? "直接提问" : `操作建议：${modeLabels[mode]}`}</Tag>
        <Dropdown
          menu={{
            items: operationItems,
            onClick: ({ key }) => onModeChange(key as ChatMode),
          }}
          trigger={["click"]}
        >
          <Button size="small" icon={<MoreOutlined />} aria-label="更多研究操作">更多研究操作</Button>
        </Dropdown>
        {mode !== "chat" && <Button size="small" type="link" onClick={() => onModeChange("chat")}>回到提问</Button>}
      </Space>
      {workspaceEnabled && <Space wrap size={[8, 8]}>
        <Select
          allowClear
          showSearch
          value={researchPlanId}
          onChange={onResearchPlanChange}
          options={planOptions}
          placeholder="研究计划（可选）"
          notFoundContent="暂无已确认研究计划"
          style={{ minWidth: 250, maxWidth: 360 }}
          optionFilterProp="label"
          aria-label="研究计划上下文"
        />
        {researchPlanId && sourceOptions.length > 0 && <Select
          mode="multiple"
          allowClear
          showSearch
          value={sourceArtifactIds}
          onChange={onSourceArtifactChange}
          options={sourceOptions}
          placeholder="补充报告或代码草案（可选）"
          maxTagCount={2}
          style={{ minWidth: 250, maxWidth: 360 }}
          optionFilterProp="label"
          aria-label="补充研究来源"
        />}
      </Space>}
    </div>
    <Typography.Text className="gm-chat-agent-hint" type="secondary">{hint}</Typography.Text>
    <Input.TextArea
      value={value}
      autoSize={{ minRows: 1, maxRows: 7 }}
      maxLength={12000}
      placeholder={placeholder}
      aria-label="输入消息"
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={(event) => {
        if (shouldSendOnEnter(event)) {
          event.preventDefault();
          send();
        }
      }}
    />
    <div className="gm-chat-composer-footer">
      <Typography.Text type="secondary">Enter 发送，Shift + Enter 换行</Typography.Text>
      <Space>
        <Typography.Text type="secondary">{value.length}/12000</Typography.Text>
        <Button type="primary" icon={<SendOutlined />} loading={loading} disabled={sendDisabled} onClick={send}>
          {mode === "chat" ? "发送" : "查看启动建议"}
        </Button>
      </Space>
    </div>
  </div>;
}
