import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Drawer, Grid, Modal, Result, Spin, message } from "antd";
import { useNavigate, useParams } from "react-router-dom";
import chatApi, { type ChatConversation, type ChatMessage } from "../api/chat";
import workspaceApi from "../api/workspace";
import agentApi, { type AgentRunDetail } from "../api/agent";
import { discoverApi, type ResearchPlan } from "../api/discover";
import type { Workspace } from "../api/types/workspace";
import { chatConversationPath, chatErrorMessage, sortChatMessages } from "../state/chatState";
import ChatComposer, { type ChatMode } from "../components/chat/ChatComposer";
import ChatEmptyState from "../components/chat/ChatEmptyState";
import ChatHeader from "../components/chat/ChatHeader";
import ChatHistory from "../components/chat/ChatHistory";
import ChatMessages from "../components/chat/ChatMessages";

const localMessage = (conversationId: string, role: "user" | "assistant", content: string, sequence: number): ChatMessage => ({ id: `local-${role}-${Date.now()}-${sequence}`, conversation_id: conversationId, role, content, status: role === "assistant" ? "generating" : "completed", error_message: null, sequence, model: null, prompt_tokens: null, completion_tokens: null, total_tokens: null, grounding_status: "not_requested", citations: [], created_at: new Date().toISOString(), updated_at: new Date().toISOString() });

export default function ChatPage() {
  const { conversationId, id: routeWorkspaceId } = useParams<{ conversationId: string; id: string }>();
  const navigate = useNavigate();
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<ChatConversation[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | undefined>(routeWorkspaceId);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyQuery, setHistoryQuery] = useState("");
  const [conversation, setConversation] = useState<ChatConversation | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [conversationError, setConversationError] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [retryingId, setRetryingId] = useState<string>();
  const [mode, setMode] = useState<ChatMode>("chat");
  const [researchPlans, setResearchPlans] = useState<ResearchPlan[]>([]);
  const [researchPlanId, setResearchPlanId] = useState<string>();
  const [agentRuns, setAgentRuns] = useState<AgentRunDetail[]>([]);
  const [agentActionId, setAgentActionId] = useState<string>();
  const messagesRef = useRef<HTMLDivElement>(null);
  const workspaceNames = Object.fromEntries(workspaces.map((workspace) => [workspace.id, workspace.name]));
  const activeWorkspaceId = conversation?.workspace_id ?? selectedWorkspaceId;
  const activeWorkspaceName = activeWorkspaceId ? workspaceNames[activeWorkspaceId] : undefined;

  const loadAgentRuns = useCallback(async (workspaceId: string, targetConversationId: string) => {
    try {
      const listed = await agentApi.list(workspaceId, { conversation_id: targetConversationId, limit: 50 });
      const details = await Promise.all(listed.items.map((run) => agentApi.get(workspaceId, run.id)));
      setAgentRuns(details);
    } catch (error) {
      message.error(chatErrorMessage(error));
    }
  }, []);

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
  useEffect(() => { workspaceApi.list({ limit: 200 }).then((result) => setWorkspaces(result.items)).catch(() => setWorkspaces([])); }, []);
  useEffect(() => { if (!conversationId) setSelectedWorkspaceId(routeWorkspaceId); }, [conversationId, routeWorkspaceId]);
  useEffect(() => { if (conversationId) void loadConversation(conversationId); else { setConversation(null); setMessages([]); setConversationError(null); } }, [conversationId, loadConversation]);
  useEffect(() => { if (conversation) setSelectedWorkspaceId(conversation.workspace_id ?? undefined); }, [conversation]);
  useEffect(() => { const node = messagesRef.current; if (node) node.scrollTop = node.scrollHeight; }, [messages, sending]);
  useEffect(() => {
    if (!activeWorkspaceId) { setResearchPlans([]); setResearchPlanId(undefined); setMode("chat"); return; }
    discoverApi.listPlans(activeWorkspaceId, { limit: 100 }).then((response) => setResearchPlans(response.items)).catch(() => setResearchPlans([]));
  }, [activeWorkspaceId]);
  useEffect(() => {
    if (conversationId && activeWorkspaceId) void loadAgentRuns(activeWorkspaceId, conversationId);
    else setAgentRuns([]);
  }, [activeWorkspaceId, conversationId, loadAgentRuns]);
  useEffect(() => {
    if (!conversationId || !activeWorkspaceId || !agentRuns.some((run) => ["queued", "running"].includes(run.status))) return;
    const timer = window.setInterval(() => { void loadConversation(conversationId); void loadAgentRuns(activeWorkspaceId, conversationId); }, 1800);
    return () => window.clearInterval(timer);
  }, [activeWorkspaceId, agentRuns, conversationId, loadAgentRuns, loadConversation]);

  const selectConversation = (item: ChatConversation) => { navigate(chatConversationPath(item)); setHistoryOpen(false); };
  const newConversation = () => { navigate(routeWorkspaceId ? `/workspaces/${routeWorkspaceId}/assistant` : "/chat/new"); setInput(""); setHistoryOpen(false); };
  const changeWorkspace = (workspaceId?: string) => {
    setSelectedWorkspaceId(workspaceId);
    if (workspaceId) navigate(`/workspaces/${workspaceId}/assistant`);
    else if (routeWorkspaceId) navigate("/chat/new");
  };
  const startAgent = async (content: string) => {
    if (!activeWorkspaceId || mode === "chat") return;
    setSending(true);
    setInput("");
    try {
      let targetConversationId = conversationId;
      if (!targetConversationId) {
        const created = await chatApi.createConversation(content.slice(0, 38), activeWorkspaceId);
        targetConversationId = created.id;
        setConversation(created);
      }
      const planOrNone = researchPlanId || undefined; // P1.5: W7 works standalone without a plan
      const agentInput = mode === "research_plan"
        ? {}
        : mode === "code_generation"
          ? { research_plan_id: researchPlanId, framework: "PyTorch" }
          : mode === "respond"
            ? { research_plan_id: planOrNone, reviewer_comments: content }
            : { research_plan_id: planOrNone };
      const run = await agentApi.start(activeWorkspaceId, {
        agent_type: mode,
        prompt: content,
        conversation_id: targetConversationId,
        input: agentInput,
      });
      if (!conversationId) navigate(`/workspaces/${activeWorkspaceId}/assistant/${targetConversationId}`, { replace: true });
      await Promise.all([loadConversation(targetConversationId), loadAgentRuns(activeWorkspaceId, targetConversationId)]);
      const agentLabel = mode === "research_plan" ? "研究计划" : mode === "code_generation" ? "代码生成" : mode === "analyze" ? "结果分析" : mode === "write" ? "论文写作" : mode === "respond" ? "审稿回复" : "Agent";
      message.success(`${agentLabel} Agent 已启动`);
      setAgentActionId(run.id);
      window.setTimeout(() => setAgentActionId(undefined), 500);
      void loadHistory();
    } catch (error) {
      setInput(content);
      message.error(chatErrorMessage(error));
    } finally { setSending(false); }
  };

  const send = async (content: string) => {
    if (mode !== "chat") { await startAgent(content); return; }
    let targetId = conversationId;
    setInput("");
    if (!targetId) {
      try {
        const created = await chatApi.createConversation(content.slice(0, 38), selectedWorkspaceId);
        targetId = created.id;
        setConversation(created);
        navigate(chatConversationPath(created), { replace: true });
      } catch (error) {
        message.error(chatErrorMessage(error));
        return;
      }
    }
    setSending(true);
    const assistantKey = `local-stream-${Date.now()}`;
    const optimisticUser = localMessage(targetId, "user", content, messages.length + 1);
    const optimisticAssistant = { ...localMessage(targetId, "assistant", "", messages.length + 2), id: assistantKey };
    setMessages((current) => [...current, optimisticUser, optimisticAssistant]);
    // Browser paint is frame-driven: even per-token DOM updates collapse to a
    // single paint if the tokens arrive within one frame. Throttle rendering to
    // a fixed cadence (~20 chars / 60ms) so the UI visibly streams regardless
    // of how the browser coalesces SSE chunks.
    let pendingDelta = "";
    let streamTimer: number | null = null;
    const appendDelta = (delta: string) => {
      pendingDelta += delta;
      if (streamTimer == null) {
        streamTimer = window.setInterval(() => {
          if (pendingDelta) {
            const slice = pendingDelta.slice(0, 20);
            pendingDelta = pendingDelta.slice(20);
            setMessages((current) => current.map((m) => m.id === assistantKey ? { ...m, content: m.content + slice } : m));
          }
          if (!pendingDelta && streamTimer != null) {
            window.clearInterval(streamTimer);
            streamTimer = null;
          }
        }, 60);
      }
    };
    try {
      await streamAssistant(targetId, content, appendDelta);
      // Let the throttled renderer flush any remaining buffered tokens before
      // loadConversation replaces the optimistic message with the full one.
      await new Promise<void>((resolve) => {
        const wait = () => {
          if (streamTimer != null || pendingDelta) window.setTimeout(wait, 50);
          else resolve();
        };
        wait();
      });
      await Promise.all([loadConversation(targetId), loadHistory()]);
    } catch (error) {
      setMessages((current) => current.map((m) => m.id === assistantKey ? { ...m, status: "failed" as const } : m));
      message.error(chatErrorMessage(error));
      void loadHistory();
    } finally { setSending(false); }
  };

  const streamAssistant = async (conversationId: string, content: string, appendDelta: (d: string) => void) => {
    const resp = await chatApi.streamSend(conversationId, content);
    if (!resp.ok || !resp.body) throw new Error("流式响应不可用");
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data: ")) continue;
        try {
          const event = JSON.parse(line.slice(6)) as { type?: string; content?: string };
          if (event.type === "token" && typeof event.content === "string") appendDelta(event.content);
        } catch { /* ignore malformed SSE line */ }
      }
    }
  };

  const refreshAgent = async (run: AgentRunDetail) => {
    if (!activeWorkspaceId) return;
    setAgentActionId(run.id);
    try { await Promise.all([loadAgentRuns(activeWorkspaceId, run.conversation_id ?? conversationId ?? ""), conversationId ? loadConversation(conversationId) : Promise.resolve()]); }
    finally { setAgentActionId(undefined); }
  };
  const confirmAgent = async (run: AgentRunDetail) => {
    if (!activeWorkspaceId) return;
    setAgentActionId(run.id);
    try {
      await agentApi.confirm(activeWorkspaceId, run.id);
      message.success("研究计划已保存到研究中心");
      await refreshAgent(run);
      const response = await discoverApi.listPlans(activeWorkspaceId, { limit: 100 });
      setResearchPlans(response.items);
    } catch (error) { message.error(chatErrorMessage(error)); }
    finally { setAgentActionId(undefined); }
  };
  const cancelAgent = async (run: AgentRunDetail) => {
    if (!activeWorkspaceId) return;
    setAgentActionId(run.id);
    try { await agentApi.cancel(activeWorkspaceId, run.id); message.success("Agent 已停止"); await refreshAgent(run); }
    catch (error) { message.error(chatErrorMessage(error)); }
    finally { setAgentActionId(undefined); }
  };
  const validateAgent = async (run: AgentRunDetail) => {
    if (!activeWorkspaceId) return;
    try { await agentApi.validate(activeWorkspaceId, run.id); message.success("已提交隔离验证，可在处理中心查看结果"); }
    catch (error) { message.error(chatErrorMessage(error)); }
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

  const historyPanel = <ChatHistory items={history} selectedId={conversationId} loading={historyLoading} query={historyQuery} workspaceNames={workspaceNames} onQueryChange={setHistoryQuery} onNew={newConversation} onSelect={selectConversation} onRename={rename} onDelete={remove} />;
  return <div className="gm-chat-page"><div className="gm-chat-layout">{!isMobile && <aside className="gm-chat-sidebar">{historyPanel}</aside>}<main className="gm-chat-main"><ChatHeader title={conversation?.title ?? "新对话"} workspaces={workspaces} workspaceId={activeWorkspaceId} scopeLocked={Boolean(conversation)} onWorkspaceChange={changeWorkspace} onOpenHistory={() => setHistoryOpen(true)} /><div className="gm-chat-scroll" ref={messagesRef}>{conversationError ? <Result status="404" title="找不到这段对话" subTitle={conversationError} extra={<Button type="primary" onClick={newConversation}>开始新对话</Button>} /> : loadingConversation ? <div className="gm-chat-loading"><Spin /></div> : messages.length === 0 ? <ChatEmptyState onExample={setInput} workspaceName={activeWorkspaceName} /> : <ChatMessages conversationId={conversationId} messages={messages} agentRuns={agentRuns} onRetry={retry} retryingId={retryingId} agentActionId={agentActionId} onRefreshAgent={(run) => void refreshAgent(run)} onConfirmAgent={(run) => void confirmAgent(run)} onCancelAgent={(run) => void cancelAgent(run)} onValidateAgent={(run) => void validateAgent(run)} onDownloadAgent={(run) => activeWorkspaceId ? void agentApi.downloadBundle(activeWorkspaceId, run.id) : undefined} />}</div>{activeWorkspaceId ? <Alert className="gm-chat-scope-note" type="success" showIcon message={`正在使用“${activeWorkspaceName ?? "课题空间"}”中已索引的论文回答；引用可定位到解析原文。`} /> : conversation && <Alert className="gm-chat-scope-note" type="info" showIcon message="当前是普通 AI 对话，不会自动检索论文或知识库。" />}{sending && <div className="gm-chat-sending-note">{mode === "chat" ? "正在检索并组织回答，请稍候…" : "正在创建 Agent 任务，请稍候…"}</div>}<ChatComposer value={input} onChange={setInput} onSend={(value) => void send(value)} loading={sending || Boolean(retryingId)} workspaceEnabled={Boolean(activeWorkspaceId)} mode={mode} onModeChange={setMode} planOptions={researchPlans.map((plan) => ({ value: plan.id, label: plan.research_question }))} researchPlanId={researchPlanId} onResearchPlanChange={setResearchPlanId} /></main></div><Drawer title="历史对话" placement="left" open={isMobile && historyOpen} onClose={() => setHistoryOpen(false)} width={300}>{historyPanel}</Drawer></div>;
}
