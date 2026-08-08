import { useState } from "react";
import { Button, Input, Segmented, Select, Space, Tooltip, Typography } from "antd";
import { CodeOutlined, ExperimentOutlined, MessageOutlined, SendOutlined } from "@ant-design/icons";
import { shouldSendOnEnter } from "../../state/chatState";

export type ChatMode = "chat" | "research_plan" | "code_generation";

interface Props {
  loading: boolean;
  onSend: (value: string) => void;
  value: string;
  onChange: (value: string) => void;
  workspaceEnabled: boolean;
  mode: ChatMode;
  onModeChange: (mode: ChatMode) => void;
  planOptions: { label: string; value: string }[];
  researchPlanId?: string;
  onResearchPlanChange: (value?: string) => void;
}

export default function ChatComposer({ loading, onSend, value, onChange, workspaceEnabled, mode, onModeChange, planOptions, researchPlanId, onResearchPlanChange }: Props) {
  const [focused, setFocused] = useState(false);
  const sendDisabled = !value.trim() || loading || (mode === "code_generation" && !researchPlanId);
  const send = () => { const content = value.trim(); if (sendDisabled) return; onSend(content); };
  const placeholder = mode === "research_plan" ? "描述研究目标、资源约束或希望验证的假设…" : mode === "code_generation" ? "描述希望生成的实验代码、框架或运行约束…" : "输入你的问题…";
  return <div className={`gm-chat-composer ${focused ? "is-focused" : ""}`}>
    <div className="gm-chat-agent-toolbar">
      <Tooltip title={workspaceEnabled ? undefined : "请先选择课题空间后使用 Agent"}>
        <Segmented<ChatMode>
          value={mode}
          onChange={onModeChange}
          options={[
            { label: <Space size={5}><MessageOutlined />资料问答</Space>, value: "chat" },
            { label: <Space size={5}><ExperimentOutlined />生成研究计划</Space>, value: "research_plan", disabled: !workspaceEnabled },
            { label: <Space size={5}><CodeOutlined />代码生成</Space>, value: "code_generation", disabled: !workspaceEnabled },
          ]}
        />
      </Tooltip>
      {mode === "code_generation" && <Select allowClear showSearch value={researchPlanId} onChange={onResearchPlanChange} options={planOptions} placeholder={planOptions.length ? "选择研究计划" : "请先在研究中心确认计划"} style={{ minWidth: 260 }} optionFilterProp="label" />}
    </div>
    {mode !== "chat" && <Typography.Text className="gm-chat-agent-hint" type="secondary">{mode === "research_plan" ? "Agent 将检索工作区证据并生成结构化草案，确认后才会保存。" : "Agent 将依据所选计划生成可预览、可下载的项目文件，不会自动执行代码。"}</Typography.Text>}
    <Input.TextArea value={value} autoSize={{ minRows: 1, maxRows: 7 }} maxLength={12000} placeholder={placeholder} aria-label="输入消息" onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} onChange={(event) => onChange(event.target.value)} onKeyDown={(event) => { if (shouldSendOnEnter(event)) { event.preventDefault(); send(); } }} />
    <div className="gm-chat-composer-footer"><Typography.Text type="secondary">Enter 发送，Shift + Enter 换行</Typography.Text><Space><Typography.Text type="secondary">{value.length}/12000</Typography.Text><Button type="primary" icon={<SendOutlined />} loading={loading} disabled={sendDisabled} onClick={send}>{mode === "chat" ? "发送" : "启动 Agent"}</Button></Space></div>
  </div>;
}
