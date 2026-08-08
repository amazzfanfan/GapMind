import apiClient from "./client";

export interface ChatConversation {
  id: string;
  title: string;
  workspace_id?: string | null;
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
  grounding_status?: "not_requested" | "grounded" | "no_evidence" | "retrieval_failed";
  citations?: ChatMessageEvidence[];
  citation_check?: CitationCheck | null;
  created_at: string;
  updated_at: string;
}

export interface CitationCheck {
  referenced: number[];
  broken: number[];
  ok: boolean;
  grounded_without_citations: boolean;
}

export interface ChatMessageEvidence {
  id: string;
  message_id: string;
  workspace_id: string;
  paper_id: string | null;
  artifact_id: string | null;
  chunk_id: string | null;
  paper_title: string | null;
  section: string | null;
  excerpt: string;
  start_char: number | null;
  end_char: number | null;
  score: number;
  rank: number;
  created_at: string;
  updated_at: string;
}

export interface ChatEvidenceContext {
  evidence: ChatMessageEvidence;
  available: boolean;
  artifact_kind: string | null;
  filename: string | null;
  content: string | null;
  message: string | null;
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
  async listConversations(params: { query?: string; workspace_id?: string; limit?: number; offset?: number } = {}) {
    const { data } = await apiClient.get<ChatConversationListResponse>("/chat/conversations", { params });
    return data;
  },
  async getConversation(id: string) {
    const { data } = await apiClient.get<ChatConversationDetail>(`/chat/conversations/${id}`);
    return data;
  },
  async createConversation(title?: string, workspaceId?: string) {
    const { data } = await apiClient.post<ChatConversation>("/chat/conversations", {
      title: title ?? null,
      workspace_id: workspaceId ?? null,
    });
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
  async sendNew(content: string, workspaceId?: string) {
    const { data } = await apiClient.post<ChatSendResponse>("/chat/conversations/send", {
      content,
      workspace_id: workspaceId ?? null,
    });
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
  async getEvidenceContext(conversationId: string, messageId: string, evidenceId: string) {
    const { data } = await apiClient.get<ChatEvidenceContext>(
      `/chat/conversations/${conversationId}/messages/${messageId}/evidence/${evidenceId}/context`,
    );
    return data;
  },
};

export default chatApi;
