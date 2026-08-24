import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Button, Card, Col, Empty, List, Row, Skeleton, Space, Tag, Typography } from "antd";
import { ArrowRightOutlined, BulbOutlined, MessageOutlined, ProjectOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import chatApi, { type ChatConversation } from "../api/chat";
import workspaceApi from "../api/workspace";
import type { Workspace } from "../api/types/workspace";
import { chatConversationPath } from "../state/chatState";
import { isIndependentWorkspaceName } from "../state/independentMode";
import { requestErrorMessage } from "../state/requestFeedback";

const { Paragraph, Text, Title } = Typography;

export default function ChatHubPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [conversationError, setConversationError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const [workspaceResult, conversationResult] = await Promise.allSettled([
      workspaceApi.list({ limit: 200 }),
      chatApi.listConversations({ limit: 100 }),
    ]);
    if (workspaceResult.status === "fulfilled") {
      setWorkspaces(workspaceResult.value.items);
      setWorkspaceError(null);
    } else {
      setWorkspaces([]);
      setWorkspaceError(requestErrorMessage(workspaceResult.reason, "课题空间暂时无法加载，请稍后重试。"));
    }
    if (conversationResult.status === "fulfilled") {
      setConversations(conversationResult.value.items);
      setConversationError(null);
    } else {
      setConversations([]);
      setConversationError(requestErrorMessage(conversationResult.reason, "对话记录暂时无法加载，请稍后重试。"));
    }
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  const assistantWorkspaces = useMemo(
    () => workspaces.filter((workspace) => !isIndependentWorkspaceName(workspace.name)),
    [workspaces],
  );
  const independentWorkspaceIds = useMemo(
    () => new Set(workspaces.filter((workspace) => isIndependentWorkspaceName(workspace.name)).map((workspace) => workspace.id)),
    [workspaces],
  );

  const workspaceNames = useMemo(
    () => Object.fromEntries(assistantWorkspaces.map((workspace) => [workspace.id, workspace.name])),
    [assistantWorkspaces],
  );
  const conversationCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    conversations.forEach((conversation) => {
      if (conversation.workspace_id) counts[conversation.workspace_id] = (counts[conversation.workspace_id] ?? 0) + 1;
    });
    return counts;
  }, [conversations]);
  const recent = conversations.slice(0, 8);

  return <div className="gm-assistant-hub">
    <section className="gm-assistant-hero">
      <div><Text className="gm-eyebrow">Graph ML Research Copilot</Text><Title level={2}>图机器学习科研助手</Title><Paragraph>面向图机器学习与图神经网络研究：从论文证据问答，到研究机会核验、Critic 收窄和人工确认。当前回答只基于所选课题空间的资料，AI 产物默认是待审阅草稿。</Paragraph></div>
      <Button icon={<BulbOutlined />} onClick={() => navigate("/chat/new")}>通用对话</Button>
    </section>

    <section className="gm-assistant-section">
      <div className="gm-assistant-section-heading"><div><Title level={4}>选择图机器学习课题空间</Title><Text type="secondary">进入课题后，AI 回答会检索该空间中已向量化的论文并附带原文证据；资料不足时不会补写无来源结论。</Text></div><Button type="link" onClick={() => navigate("/workspaces")}>管理课题空间</Button></div>
      {loading ? <Row gutter={[16, 16]}>{[1, 2, 3].map((item) => <Col xs={24} md={12} xl={8} key={item}><Card><Skeleton active paragraph={{ rows: 2 }} /></Card></Col>)}</Row> : workspaceError ? <Alert type="warning" showIcon message="课题空间暂时无法加载" description={workspaceError} action={<Button size="small" onClick={() => void load()}>重试</Button>} /> : assistantWorkspaces.length === 0 ? <Card><Empty description="还没有课题空间" image={Empty.PRESENTED_IMAGE_SIMPLE}><Button type="primary" onClick={() => navigate("/workspaces")}>创建课题空间</Button></Empty></Card> : <Row gutter={[16, 16]}>{assistantWorkspaces.map((workspace) => <Col xs={24} md={12} xl={8} key={workspace.id}><Card hoverable className="gm-assistant-workspace-card" onClick={() => navigate(`/workspaces/${workspace.id}/assistant`)}><Space direction="vertical" size={10} style={{ width: "100%" }}><div className="gm-assistant-workspace-title"><span className="gm-assistant-workspace-icon"><ProjectOutlined /></span><Title level={5}>{workspace.name}</Title><ArrowRightOutlined /></div><Paragraph type="secondary" ellipsis={{ rows: 2 }}>{workspace.topic || workspace.description || "尚未填写研究主题"}</Paragraph><Space wrap><Tag color="blue">证据对话</Tag><Text type="secondary">{conversationCounts[workspace.id] ?? 0} 段历史对话</Text></Space></Space></Card></Col>)}</Row>}
    </section>

    <Row gutter={[18, 18]} className="gm-assistant-lower-grid">
      <Col xs={24} lg={16}><Card title="最近的研究对话" extra={conversations.length > recent.length ? <Text type="secondary">显示最近 {recent.length} 条</Text> : null}>{loading ? <Skeleton active /> : conversationError ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={conversationError}><Button onClick={() => void load()}>重新加载</Button></Empty> : recent.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无对话记录" /> : <List dataSource={recent} renderItem={(conversation) => <List.Item className="gm-assistant-recent-item" onClick={() => navigate(chatConversationPath(conversation, independentWorkspaceIds))} extra={<ArrowRightOutlined />}><List.Item.Meta avatar={<span className="gm-assistant-conversation-icon"><MessageOutlined /></span>} title={conversation.title} description={conversation.workspace_id && !independentWorkspaceIds.has(conversation.workspace_id) ? workspaceNames[conversation.workspace_id] ?? "课题空间" : "通用对话"} /></List.Item>} />}</Card></Col>
      <Col xs={24} lg={8}><Card className="gm-assistant-general-card"><Space direction="vertical" size={14}><span className="gm-assistant-general-icon"><BulbOutlined /></span><div><Title level={4}>通用对话</Title><Paragraph type="secondary">用于研究思路梳理、概念解释和文字润色，不会检索课题论文，也不会生成证据引用。</Paragraph></div><Button block onClick={() => navigate("/chat/new")}>开始通用对话</Button></Space></Card></Col>
    </Row>
  </div>;
}
