import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Drawer, Grid, Modal, Result, Spin, message } from "antd";
import { useNavigate, useParams } from "react-router-dom";
import chatApi, { type ChatConversation, type ChatMessage } from "../api/chat";
import { chatErrorMessage, sortChatMessages } from "./chatState";
import ChatComposer from "../components/chat/ChatComposer";
import ChatEmptyState from "../components/chat/ChatEmptyState";
import ChatHeader from "../components/chat/ChatHeader";
import ChatHistory from "../components/chat/ChatHistory";
import ChatMessages from "../components/chat/ChatMessages";

const localMessage = (conversationId: string, role: "user" | "assistant", content: string, sequence: number): ChatMessage => ({ id: `local-${role}-${Date.now()}-${sequence}`, conversation_id: conversationId, role, content, status: role === "assistant" ? "generating" : "completed", error_message: null, sequence, model: null, prompt_tokens: null, completion_tokens: null, total_tokens: null, created_at: new Date().toISOString(), updated_at: new Date().toISOString() });

export default function ChatPage() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const navigate = useNavigate();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<ChatConversation[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyQuery, setHistoryQuery] = useState("");
  const [conversation, setConversation] = useState<ChatConversation | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [conversationError, setConversationError] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [retryingId, setRetryingId] = useState<string>();
  const messagesRef = useRef<HTMLDivElement>(null);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try { setHistory((await chatApi.listConversations({ query: historyQuery || undefined, limit: 100 })).items); }
    catch (error) { message.error(chatErrorMessage(error)); }
    finally { setHistoryLoading(false); }
  }, [historyQuery]);

  const loadConversation = useCallback(async (id: string) => {
    setLoadingConversation(true); setConversationError(null);
    try { const detail = await chatApi.getConversation(id); setConversation(detail.conversation); setMessages(sortChatMessages(detail.messages)); }
    catch (error) { setConversation(null); setMessages([]); setConversationError(chatErrorMessage(error)); }
    finally { setLoadingConversation(false); }
  }, []);

  useEffect(() => { const timer = window.setTimeout(() => void loadHistory(), 180); return () => window.clearTimeout(timer); }, [loadHistory]);
  useEffect(() => { if (conversationId) void loadConversation(conversationId); else { setConversation(null); setMessages([]); setConversationError(null); } }, [conversationId, loadConversation]);
  useEffect(() => { const node = messagesRef.current; if (node) node.scrollTop = node.scrollHeight; }, [messages, sending]);

  const selectConversation = (id: string) => { navigate(`/chat/${id}`); setHistoryOpen(false); };
  const newConversation = () => { navigate("/chat"); setInput(""); setHistoryOpen(false); };
  const send = async (content: string) => {
    const targetId = conversationId;
    const optimisticUser = localMessage(targetId ?? "new", "user", content, messages.length + 1);
    const optimisticAssistant = localMessage(targetId ?? "new", "assistant", "", messages.length + 2);
    setInput(""); setSending(true); setMessages((current) => [...current, optimisticUser, optimisticAssistant]);
    try {
      const result = targetId ? await chatApi.sendMessage(targetId, content) : await chatApi.sendNew(content);
      setConversation(result.conversation);
      setMessages((current) => [...current.filter((item) => !item.id.startsWith("local-")), result.user_message, result.assistant_message]);
      if (!targetId) navigate(`/chat/${result.conversation.id}`, { replace: true });
      void loadHistory();
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: { conversation_id?: string } } } }).response?.data?.detail;
      const failedConversationId = detail?.conversation_id;
      if (!targetId && failedConversationId) navigate(`/chat/${failedConversationId}`, { replace: true });
      if (failedConversationId) void loadConversation(failedConversationId);
      else setMessages((current) => current.map((item) => item.id === optimisticAssistant.id ? { ...item, status: "failed" as const } : item));
      message.error(chatErrorMessage(error)); void loadHistory();
    } finally { setSending(false); }
  };

  const retry = async (failed: ChatMessage) => {
    if (!conversationId) return;
    setRetryingId(failed.id);
    try { const result = await chatApi.retryMessage(conversationId, failed.id); setConversation(result.conversation); setMessages((current) => current.map((item) => item.id === failed.id ? result.assistant_message : item)); void loadHistory(); }
    catch (error) { message.error(chatErrorMessage(error)); void loadConversation(conversationId); }
    finally { setRetryingId(undefined); }
  };

  const rename = (item: ChatConversation) => {
    let nextTitle = item.title;
    Modal.confirm({ title: "重命名对话", content: <input autoFocus defaultValue={item.title} maxLength={255} onChange={(event) => { nextTitle = event.target.value; }} style={{ width: "100%", padding: 8 }} />, okText: "保存", cancelText: "取消", onOk: async () => { if (!nextTitle.trim()) { message.error("标题不能为空"); return Promise.reject(); } const updated = await chatApi.renameConversation(item.id, nextTitle.trim()); if (conversationId === item.id) setConversation(updated); void loadHistory(); } });
  };
  const remove = (item: ChatConversation) => {
    Modal.confirm({ title: "删除这段对话？", content: "删除后将从历史列表中移除，消息无法在界面中恢复。", okText: "删除", okButtonProps: { danger: true }, cancelText: "取消", onOk: async () => { try { await chatApi.deleteConversation(item.id); if (conversationId === item.id) newConversation(); void loadHistory(); message.success("已删除对话"); } catch (error) { message.error(chatErrorMessage(error)); } } });
  };

  const historyPanel = <ChatHistory items={history} selectedId={conversationId} loading={historyLoading} query={historyQuery} onQueryChange={setHistoryQuery} onNew={newConversation} onSelect={selectConversation} onRename={rename} onDelete={remove} />;
  return <div className="gm-chat-page"><div className="gm-chat-layout">{!isMobile && <aside className="gm-chat-sidebar">{historyPanel}</aside>}<main className="gm-chat-main"><ChatHeader title={conversation?.title ?? "新对话"} onOpenHistory={() => setHistoryOpen(true)} /><div className="gm-chat-scroll" ref={messagesRef}>{conversationError ? <Result status="404" title="找不到这段对话" subTitle={conversationError} extra={<Button type="primary" onClick={newConversation}>开始新对话</Button>} /> : loadingConversation ? <div className="gm-chat-loading"><Spin /></div> : messages.length === 0 ? <ChatEmptyState onExample={setInput} /> : <ChatMessages messages={messages} onRetry={retry} retryingId={retryingId} />}</div>{conversation && <Alert className="gm-chat-scope-note" type="info" showIcon message="普通 AI 对话不会自动检索论文、知识库或 Discover。" />}{sending && <div className="gm-chat-sending-note">正在思考，请稍候…</div>}<ChatComposer value={input} onChange={setInput} onSend={send} loading={sending || Boolean(retryingId)} /></main></div><Drawer title="历史对话" placement="left" open={isMobile && historyOpen} onClose={() => setHistoryOpen(false)} width={300}>{historyPanel}</Drawer></div>;
}
