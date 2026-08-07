import { useEffect, useMemo, useState } from "react";
import { App, Button, Card, Col, Empty, List, Row, Skeleton, Space, Tag, Typography } from "antd";
import { ArrowRightOutlined, BulbOutlined, MessageOutlined, ProjectOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import chatApi, { type ChatConversation } from "../api/chat";
import workspaceApi from "../api/workspace";
import type { Workspace } from "../api/types/workspace";
import { chatConversationPath } from "../state/chatState";

const { Paragraph, Text, Title } = Typography;

export default function ChatHubPage() {
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [loading, setLoading] = useState(true);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [conversations, setConversations] = useState<ChatConversation[]>([]);

  useEffect(() => {
    Promise.all([
      workspaceApi.list({ limit: 200 }),
      chatApi.listConversations({ limit: 100 }),
    ])
      .then(([workspaceResult, conversationResult]) => {
        setWorkspaces(workspaceResult.items);
        setConversations(conversationResult.items);
      })
      .catch(() => message.error("AI 助手中心加载失败，请稍后重试。"))
      .finally(() => setLoading(false));
  }, [message]);

  const workspaceNames = useMemo(
    () => Object.fromEntries(workspaces.map((workspace) => [workspace.id, workspace.name])),
    [workspaces],
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
      <div><Text className="gm-eyebrow">Research Copilot</Text><Title level={2}>AI 研究助手</Title><Paragraph>选择一个课题空间，基于其中已解析的论文、知识点和证据继续研究。复杂的新颖性核验仍由 Discover Workbench 完成。</Paragraph></div>
      <Button icon={<BulbOutlined />} onClick={() => navigate("/chat/new")}>通用对话</Button>
    </section>

    <section className="gm-assistant-section">
      <div className="gm-assistant-section-heading"><div><Title level={4}>选择课题空间</Title><Text type="secondary">进入课题后，AI 回答会检索该空间中已向量化的论文并附带原文证据。</Text></div><Button type="link" onClick={() => navigate("/workspaces")}>管理课题空间</Button></div>
      {loading ? <Row gutter={[16, 16]}>{[1, 2, 3].map((item) => <Col xs={24} md={12} xl={8} key={item}><Card><Skeleton active paragraph={{ rows: 2 }} /></Card></Col>)}</Row> : workspaces.length === 0 ? <Card><Empty description="还没有课题空间" image={Empty.PRESENTED_IMAGE_SIMPLE}><Button type="primary" onClick={() => navigate("/workspaces")}>创建课题空间</Button></Empty></Card> : <Row gutter={[16, 16]}>{workspaces.map((workspace) => <Col xs={24} md={12} xl={8} key={workspace.id}><Card hoverable className="gm-assistant-workspace-card" onClick={() => navigate(`/workspaces/${workspace.id}/assistant`)}><Space direction="vertical" size={10} style={{ width: "100%" }}><div className="gm-assistant-workspace-title"><span className="gm-assistant-workspace-icon"><ProjectOutlined /></span><Title level={5}>{workspace.name}</Title><ArrowRightOutlined /></div><Paragraph type="secondary" ellipsis={{ rows: 2 }}>{workspace.topic || workspace.description || "尚未填写研究主题"}</Paragraph><Space wrap><Tag color="blue">证据对话</Tag><Text type="secondary">{conversationCounts[workspace.id] ?? 0} 段历史对话</Text></Space></Space></Card></Col>)}</Row>}
    </section>

    <Row gutter={[18, 18]} className="gm-assistant-lower-grid">
      <Col xs={24} lg={16}><Card title="最近的研究对话" extra={conversations.length > recent.length ? <Text type="secondary">显示最近 {recent.length} 条</Text> : null}>{loading ? <Skeleton active /> : recent.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无对话记录" /> : <List dataSource={recent} renderItem={(conversation) => <List.Item className="gm-assistant-recent-item" onClick={() => navigate(chatConversationPath(conversation))} extra={<ArrowRightOutlined />}><List.Item.Meta avatar={<span className="gm-assistant-conversation-icon"><MessageOutlined /></span>} title={conversation.title} description={conversation.workspace_id ? workspaceNames[conversation.workspace_id] ?? "课题空间" : "通用对话"} /></List.Item>} />}</Card></Col>
      <Col xs={24} lg={8}><Card className="gm-assistant-general-card"><Space direction="vertical" size={14}><span className="gm-assistant-general-icon"><BulbOutlined /></span><div><Title level={4}>通用对话</Title><Paragraph type="secondary">用于研究思路梳理、概念解释和文字润色，不会检索课题论文，也不会生成证据引用。</Paragraph></div><Button block onClick={() => navigate("/chat/new")}>开始通用对话</Button></Space></Card></Col>
    </Row>
  </div>;
}
