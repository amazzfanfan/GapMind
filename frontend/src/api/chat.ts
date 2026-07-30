import apiClient from "./client";

export interface ChatConversation {
  id: string;
  title: string;
  model: string | null;
  last_message_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  status: "completed" | "generating" | "failed";
  error_message: string | null;
  sequence: number;
  model: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  created_at: string;
  updated_at: string;
}

export interface ChatConversationListResponse {
  items: ChatConversation[];
  total: number;
  limit: number;
  offset: number;
}

export interface ChatConversationDetail {
  conversation: ChatConversation;
  messages: ChatMessage[];
}

export interface ChatSendResponse {
  conversation: ChatConversation;
  user_message: ChatMessage;
  assistant_message: ChatMessage;
}

export const chatApi = {
  async listConversations(params: { query?: string; limit?: number; offset?: number } = {}) {
    const { data } = await apiClient.get<ChatConversationListResponse>("/chat/conversations", { params });
    return data;
  },
  async getConversation(id: string) {
    const { data } = await apiClient.get<ChatConversationDetail>(`/chat/conversations/${id}`);
    return data;
  },
  async createConversation(title?: string) {
    const { data } = await apiClient.post<ChatConversation>("/chat/conversations", { title: title ?? null });
    return data;
  },
  async renameConversation(id: string, title: string) {
    const { data } = await apiClient.patch<ChatConversation>(`/chat/conversations/${id}`, { title });
    return data;
  },
  async deleteConversation(id: string) {
    const { data } = await apiClient.delete<{ id: string; deleted: boolean }>(`/chat/conversations/${id}`);
    return data;
  },
  async sendNew(content: string) {
    const { data } = await apiClient.post<ChatSendResponse>("/chat/conversations/send", { content });
    return data;
  },
  async sendMessage(id: string, content: string) {
    const { data } = await apiClient.post<ChatSendResponse>(`/chat/conversations/${id}/messages`, { content });
    return data;
  },
  async retryMessage(conversationId: string, assistantMessageId: string) {
    const { data } = await apiClient.post<ChatSendResponse>(
      `/chat/conversations/${conversationId}/messages/${assistantMessageId}/retry`,
    );
    return data;
  },
};

export default chatApi;
