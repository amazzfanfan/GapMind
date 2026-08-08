import { useState } from "react";
import { Button, Empty, Space, Spin, Tooltip, Typography } from "antd";
import { CheckOutlined, CopyOutlined, ReloadOutlined } from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "../../api/chat";
import ChatCitations from "./ChatCitations";
import ChatAgentRunCard from "./ChatAgentRunCard";
import type { AgentRunDetail } from "../../api/agent";

interface Props { conversationId?: string; messages: ChatMessage[]; agentRuns?: AgentRunDetail[]; onRetry: (message: ChatMessage) => void; retryingId?: string; agentActionId?: string; onRefreshAgent: (run: AgentRunDetail) => void; onConfirmAgent: (run: AgentRunDetail) => void; onCancelAgent: (run: AgentRunDetail) => void; onValidateAgent: (run: AgentRunDetail) => void; onDownloadAgent: (run: AgentRunDetail) => void; }

export default function ChatMessages({ conversationId, messages, agentRuns = [], onRetry, retryingId, agentActionId, onRefreshAgent, onConfirmAgent, onCancelAgent, onValidateAgent, onDownloadAgent }: Props) {
  if (messages.length === 0) return <Empty className="gm-chat-empty-messages" image={Empty.PRESENTED_IMAGE_SIMPLE} description="开始一段新的研究对话" />;
  const byAssistant = new Map(agentRuns.map((run) => [run.assistant_message_id, run]));
  return <div className="gm-chat-messages">{messages.map((message) => {
    const run = byAssistant.get(message.id);
    return <div key={message.id}>{run ? <><ChatAgentRunCard run={run} loading={agentActionId === run.id} onRefresh={() => onRefreshAgent(run)} onConfirm={() => onConfirmAgent(run)} onCancel={() => onCancelAgent(run)} onValidate={() => onValidateAgent(run)} onDownload={() => onDownloadAgent(run)} />{conversationId && (message.citations?.length ?? 0) > 0 && <div className="gm-agent-citations"><ChatCitations conversationId={conversationId} messageId={message.id} citations={message.citations ?? []} /></div>}</> : <ChatMessageItem conversationId={conversationId} message={message} onRetry={onRetry} retrying={retryingId === message.id} />}</div>;
  })}</div>;
}

function ChatMessageItem({ conversationId, message, onRetry, retrying }: { conversationId?: string; message: ChatMessage; onRetry: (message: ChatMessage) => void; retrying: boolean }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard?.writeText(message.content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };
  const isUser = message.role === "user";
  return <article className={`gm-chat-message ${isUser ? "is-user" : "is-assistant"}`}>
    <div className="gm-chat-message-body">
      {message.status === "generating" ? <Space><Spin size="small" /><Typography.Text type="secondary">正在思考…</Typography.Text></Space> : message.status === "failed" ? <div><Typography.Text type="danger">回答失败，请重试。</Typography.Text><div><Button type="link" size="small" icon={<ReloadOutlined />} loading={retrying} onClick={() => onRetry(message)}>重新尝试</Button></div></div> : isUser ? <Typography.Paragraph className="gm-chat-plain-text">{message.content}</Typography.Paragraph> : <div className="gm-chat-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown></div>}
      {!isUser && message.status === "completed" && message.grounding_status === "no_evidence" && <Typography.Text type="warning">本次没有使用工作区证据。</Typography.Text>}
      {!isUser && message.status === "completed" && message.citation_check && !message.citation_check.ok && <Typography.Text type="danger">检测到失效引用：[E{message.citation_check.broken.join("]、[E")}] 未找到对应证据，请核对来源。</Typography.Text>}
      {!isUser && message.status === "completed" && message.citation_check?.grounded_without_citations && <Typography.Text type="warning">已使用工作区证据，但回答未标注 [E] 引用，关键结论可能缺少直接支撑。</Typography.Text>}
      {!isUser && conversationId && (message.citations?.length ?? 0) > 0 && <ChatCitations conversationId={conversationId} messageId={message.id} citations={message.citations ?? []} />}
    </div>
    {message.status === "completed" && <div className="gm-chat-message-actions"><Tooltip title={copied ? "已复制" : "复制"}><Button type="text" size="small" aria-label="复制消息" icon={copied ? <CheckOutlined /> : <CopyOutlined />} onClick={() => void copy()} /></Tooltip></div>}
  </article>;
}
