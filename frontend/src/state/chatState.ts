import axios from "axios";
import type { ChatConversation, ChatMessage } from "../api/chat";

export function truncateChatTitle(title: string, maxLength = 38): string {
  const normalized = title.replace(/\s+/g, " ").trim();
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}…` : normalized;
}

export function sortChatMessages(messages: ChatMessage[]): ChatMessage[] {
  return [...messages].sort((a, b) => a.sequence - b.sequence);
}

export function chatConversationPath(conversation: ChatConversation): string {
  return conversation.workspace_id
    ? `/workspaces/${conversation.workspace_id}/assistant/${conversation.id}`
    : `/chat/${conversation.id}`;
}

export function shouldSendOnEnter(event: { key: string; shiftKey: boolean; nativeEvent?: { isComposing?: boolean } }): boolean {
  return event.key === "Enter" && !event.shiftKey && !event.nativeEvent?.isComposing;
}

export function conversationGroupLabel(dateValue: string | null): "今天" | "最近 7 天" | "更早" {
  if (!dateValue) return "更早";
  const date = new Date(dateValue);
  const now = new Date();
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const timestamp = date.getTime();
  if (timestamp >= startToday) return "今天";
  if (timestamp >= startToday - 6 * 24 * 60 * 60 * 1000) return "最近 7 天";
  return "更早";
}

export function groupConversations(conversations: ChatConversation[]): Array<{ label: string; items: ChatConversation[] }> {
  const groups = new Map<string, ChatConversation[]>();
  for (const conversation of conversations) {
    const label = conversationGroupLabel(conversation.last_message_at ?? conversation.updated_at);
    groups.set(label, [...(groups.get(label) ?? []), conversation]);
  }
  return ["今天", "最近 7 天", "更早"]
    .map((label) => ({ label, items: groups.get(label) ?? [] }))
    .filter((group) => group.items.length > 0);
}

export function chatErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "object" && detail?.message) return String(detail.message);
    if (error.response?.status === 404) return "这个对话不存在，可能已经被删除。";
    if (error.response?.status === 409) return "当前对话正在生成回答，请稍候再发送。";
    if (error.response?.status === 503) return "AI 服务尚未配置，请联系管理员。";
    if (error.response?.status === 502) return "AI 服务暂时不可用，请稍后重试。";
  }
  return "操作失败，请稍后重试。";
}
