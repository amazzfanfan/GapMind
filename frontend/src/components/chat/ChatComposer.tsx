import { useState } from "react";
import { Button, Input, Segmented, Select, Space, Typography } from "antd";
import { CodeOutlined, ExperimentOutlined, FileSearchOutlined, FileTextOutlined, MessageOutlined, SendOutlined } from "@ant-design/icons";
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
  planOptions: { label: string; value: string }[];
  researchPlanId?: string;
  onResearchPlanChange: (value?: string) => void;
}

// Agents that may bind a research plan (plan Select shows for these). Only
// code_generation REQUIRES one; analyze/write/respond work standalone (P1.5).
const PLAN_BIND_MODES: ChatMode[] = ["code_generation", "analyze", "write", "respond"];

export default function ChatComposer({ loading, onSend, value, onChange, workspaceEnabled, mode, onModeChange, planOptions, researchPlanId, onResearchPlanChange }: Props) {
  const [focused, setFocused] = useState(false);
  const canBindPlan = PLAN_BIND_MODES.includes(mode);
  const sendDisabled = !value.trim() || loading || (mode === "code_generation" && !researchPlanId);
  const send = () => { const content = value.trim(); if (sendDisabled) return; onSend(content); };
  const placeholder = mode === "research_plan" ? "描述研究目标、资源约束或希望验证的假设…"
    : mode === "code_generation" ? "描述希望生成的实验代码、框架或运行约束…"
    : mode === "analyze" ? "粘贴实验结果（JSON）或描述实验结论…"
    : mode === "write" ? "描述论文主题、目标章节或写作重点…"
    : mode === "respond" ? "粘贴审稿意见，逐条回应…"
    : "输入你的问题…";
  const hint = mode === "research_plan" ? "Agent 将检索工作区证据并生成结构化草案，确认后才会保存。"
    : mode === "code_generation" ? "Agent 将依据所选计划生成可预览、可下载的项目文件，不会自动执行代码。"
    : mode === "analyze" ? (workspaceEnabled ? "Agent 将对照研究计划的证伪标准与指标判定结论，并回链证据。" : "独立模式：粘贴实验数据即可分析，无需课题空间/研究计划。")
    : mode === "write" ? (workspaceEnabled ? "Agent 将基于计划与工作区证据生成论文章节草稿，回链证据。" : "独立模式：提供研究内容即可生成论文章节草稿。")
    : mode === "respond" ? (workspaceEnabled ? "Agent 将逐条回应审稿意见，回应依据回链证据。" : "独立模式：粘贴审稿意见即可逐条回应，无需课题空间。")
    : "";
  return <div className={`gm-chat-composer ${focused ? "is-focused" : ""}`}>
    <div className="gm-chat-agent-toolbar">
      <Segmented<ChatMode>
        value={mode}
        onChange={onModeChange}
        options={[
          { label: <Space size={5}><MessageOutlined />资料问答</Space>, value: "chat" },
          { label: <Space size={5}><ExperimentOutlined />生成研究计划</Space>, value: "research_plan", disabled: !workspaceEnabled },
          { label: <Space size={5}><CodeOutlined />代码生成</Space>, value: "code_generation", disabled: !workspaceEnabled },
          { label: <Space size={5}><FileSearchOutlined />结果分析</Space>, value: "analyze" },
          { label: <Space size={5}><FileTextOutlined />论文写作</Space>, value: "write" },
          { label: <Space size={5}><MessageOutlined />审稿回复</Space>, value: "respond" },
        ]}
      />
      {workspaceEnabled && canBindPlan && <Select allowClear showSearch value={researchPlanId} onChange={onResearchPlanChange} options={planOptions} placeholder={planOptions.length ? "选择研究计划" : "请先在研究中心确认计划"} style={{ minWidth: 260 }} optionFilterProp="label" />}
    </div>
    {mode !== "chat" && <Typography.Text className="gm-chat-agent-hint" type="secondary">{hint}</Typography.Text>}
    <Input.TextArea value={value} autoSize={{ minRows: 1, maxRows: 7 }} maxLength={12000} placeholder={placeholder} aria-label="输入消息" onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} onChange={(event) => onChange(event.target.value)} onKeyDown={(event) => { if (shouldSendOnEnter(event)) { event.preventDefault(); send(); } }} />
    <div className="gm-chat-composer-footer"><Typography.Text type="secondary">Enter 发送，Shift + Enter 换行</Typography.Text><Space><Typography.Text type="secondary">{value.length}/12000</Typography.Text><Button type="primary" icon={<SendOutlined />} loading={loading} disabled={sendDisabled} onClick={send}>{mode === "chat" ? "发送" : "启动 Agent"}</Button></Space></div>
  </div>;
}
