import { describe, expect, it } from "vitest";
import { chatConversationPath, chatErrorMessage, chatFailureMessage, groupConversations, shouldSendOnEnter, sortChatMessages, truncateChatTitle } from "./chatState";

const conversation = (id: string, date: string) => ({ id, title: id, model: null, last_message_at: date, created_at: date, updated_at: date });

describe("chat helpers", () => {
  it("groups conversations and truncates titles", () => {
    const today = new Date().toISOString();
    expect(groupConversations([conversation("today", today)])[0].label).toBe("今天");
    expect(truncateChatTitle("  a   b  ", 3)).toBe("a b");
    expect(truncateChatTitle("123456", 3)).toBe("123…");
  });

  it("sorts messages by sequence", () => {
    const base = { conversation_id: "c", role: "user" as const, content: "", status: "completed" as const, error_message: null, model: null, prompt_tokens: null, completion_tokens: null, total_tokens: null, created_at: "", updated_at: "" };
    expect(sortChatMessages([{ ...base, id: "2", sequence: 2 }, { ...base, id: "1", sequence: 1 }]).map((item) => item.id)).toEqual(["1", "2"]);
  });

  it("does not send while composing Chinese input", () => {
    expect(shouldSendOnEnter({ key: "Enter", shiftKey: false })).toBe(true);
    expect(shouldSendOnEnter({ key: "Enter", shiftKey: true })).toBe(false);
    expect(shouldSendOnEnter({ key: "Enter", shiftKey: false, nativeEvent: { isComposing: true } })).toBe(false);
  });

  it("turns API errors into friendly copy", () => {
    expect(chatErrorMessage({ response: { status: 502, data: { detail: { message: "上游错误" } } } })).toBe("操作失败，请稍后重试。");
  });

  it("keeps a safe remediation message for persisted failed chats", () => {
    expect(chatFailureMessage({ grounding_status: "retrieval_failed", error_message: "embedding provider unavailable" }))
      .toBe("工作区论文检索暂不可用，请检查向量化服务与 Milvus 后重试。");
    expect(chatFailureMessage({ grounding_status: "not_requested", error_message: "流式响应中断：客户端提前断开" }))
      .toBe("生成过程意外中断，请重新尝试。");
  });

  it("routes grounded conversations back to their workspace", () => {
    const date = new Date().toISOString();
    expect(chatConversationPath({ ...conversation("grounded", date), workspace_id: "ws-1" })).toBe("/workspaces/ws-1/assistant/grounded");
    expect(chatConversationPath({ ...conversation("general", date), workspace_id: null })).toBe("/chat/general");
    expect(chatConversationPath({ ...conversation("independent", date), workspace_id: "system-ws" }, new Set(["system-ws"]))).toBe("/chat/independent");
  });
});
