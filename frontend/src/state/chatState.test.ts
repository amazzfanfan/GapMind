import { describe, expect, it } from "vitest";
import { chatErrorMessage, groupConversations, shouldSendOnEnter, sortChatMessages, truncateChatTitle } from "./chatState";

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
});
