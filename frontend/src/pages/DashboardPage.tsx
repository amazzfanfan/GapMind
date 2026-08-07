import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Card, Col, List, Row, Space, Tag, Typography } from "antd";
import { FileSearchOutlined, PlusOutlined, RightOutlined, SettingOutlined } from "@ant-design/icons";
import { Link, useNavigate } from "react-router-dom";
import workspaceApi from "../api/workspace";
import paperApi from "../api/paper";
import taskApi from "../api/task";
import knowledgeApi from "../api/knowledge";
import { discoverApi, type DiscoverRun, type ResearchOpportunity } from "../api/discover";
import type { Workspace } from "../api/types/workspace";
import type { Task } from "../api/types/domain";
import PageHeader from "../components/common/PageHeader";
import EmptyGuide from "../components/common/EmptyGuide";
import StatusBadge from "../components/common/StatusBadge";

interface WorkspaceSummary {
  workspace: Workspace;
  papers: number | null;
  pendingTasks: Task[] | null;
  reviewKnowledge: number | null;
  waitingRuns: DiscoverRun[] | null;
  opportunities: ResearchOpportunity[] | null;
  pendingOpportunityCount: number | null;
}

export default function DashboardPage() {
  const navigate = useNavigate();
  const [summaries, setSummaries] = useState<WorkspaceSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const workspaces = (await workspaceApi.list({ limit: 8 })).items;
      const next = await Promise.all(workspaces.map(async (workspace) => {
        const [papers, tasks, knowledge, runs, opportunities] = await Promise.allSettled([
          paperApi.list(workspace.id, { limit: 1 }),
          taskApi.list(workspace.id, { limit: 100 }),
          knowledgeApi.listItems(workspace.id, { limit: 200 }),
          discoverApi.listRuns(workspace.id),
          discoverApi.listOpportunities(workspace.id, { pendingOnly: true, limit: 100 }),
        ]);
        const taskItems = tasks.status === "fulfilled" ? tasks.value.items : null;
        const runItems = runs.status === "fulfilled" ? runs.value.items : null;
        return {
          workspace,
          papers: papers.status === "fulfilled" ? papers.value.total : null,
          pendingTasks: taskItems?.filter((task) => ["queued", "running", "waiting_for_user", "failed"].includes(task.status)) ?? taskItems,
          reviewKnowledge: knowledge.status === "fulfilled" ? knowledge.value.items.filter((item) => ["candidate", "needs_review", "proposed"].includes(item.status)).length : null,
          waitingRuns: runItems?.filter((run) => ["waiting_for_user", "waiting_for_fulltext"].includes(run.status)) ?? runItems,
          opportunities: opportunities.status === "fulfilled" ? opportunities.value.items : null,
          pendingOpportunityCount: opportunities.status === "fulfilled" ? opportunities.value.total : null,
        } satisfies WorkspaceSummary;
      }));
      setSummaries(next);
    } catch {
      setSummaries([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const actions = summaries.flatMap((summary) => [
    ...(summary.pendingTasks ?? []).map((task) => ({ key: `task-${task.id}`, workspace: summary.workspace, title: task.status === "failed" ? "后台任务处理失败" : "后台任务正在处理", status: task.status, href: `/workspaces/${summary.workspace.id}/activity` })),
    ...(summary.waitingRuns ?? []).map((run) => ({ key: `run-${run.id}`, workspace: summary.workspace, title: "Discover 等待继续", status: run.status, href: `/workspaces/${summary.workspace.id}/discover?run=${run.id}` })),
    ...(summary.opportunities ?? []).map((opportunity) => ({ key: `opportunity-${opportunity.id}`, workspace: summary.workspace, title: opportunity.title, status: opportunity.status, href: `/workspaces/${summary.workspace.id}/discover?opportunity=${opportunity.id}` })),
  ]).slice(0, 8);

  return (
    <div>
      <PageHeader
        eyebrow="GapMind"
        title="继续你的研究"
        description="从课题、文献和证据出发，把下一步行动变得清晰。"
        extra={<><Link to="/workspaces"><Button type="primary" icon={<PlusOutlined />}>新建课题</Button></Link><Link to="/search"><Button icon={<FileSearchOutlined />}>全局检索</Button></Link></>}
      />

      {summaries.length === 0 && !loading ? (
        <Card><EmptyGuide description="还没有建立课题。先创建一个课题，再开始收集文献和证据。" actionText="创建第一个课题" actionIcon={<PlusOutlined />} onAction={() => navigate("/workspaces")} /></Card>
      ) : (
        <>
          {actions.length > 0 && <Card title="需要你处理" extra={<Link to="/workspaces">查看课题</Link>} style={{ marginBottom: 20 }}><List size="small" dataSource={actions} renderItem={(item) => <List.Item actions={[<Link key="open" to={item.href}><RightOutlined /></Link>]}><Space><Tag>{item.workspace.name}</Tag><Typography.Text>{item.title}</Typography.Text><StatusBadge status={item.status} /></Space></List.Item>} /></Card>}
          <Typography.Title level={4}>最近课题</Typography.Title>
          <Row gutter={[16, 16]}>
            {summaries.map((summary) => <Col xs={24} md={12} xl={8} key={summary.workspace.id}><Card className="gm-action-card" title={<Link to={`/workspaces/${summary.workspace.id}/overview`}>{summary.workspace.name}</Link>} extra={<Link to={`/workspaces/${summary.workspace.id}/settings`}><SettingOutlined /></Link>}><Typography.Paragraph type="secondary" ellipsis={{ rows: 2 }}>{summary.workspace.description || summary.workspace.topic || "尚未填写课题描述"}</Typography.Paragraph><Space wrap><Tag>{summary.papers === null ? "文献：暂不可用" : `文献 ${summary.papers} 篇`}</Tag><Tag>{summary.reviewKnowledge === null ? "知识：暂不可用" : `待审核知识 ${summary.reviewKnowledge}`}</Tag><Tag color={summary.pendingOpportunityCount ? "orange" : "default"}>{summary.pendingOpportunityCount === null ? "机会：暂不可用" : `待处理机会 ${summary.pendingOpportunityCount}`}</Tag></Space><div style={{ marginTop: 16 }}><Link to={`/workspaces/${summary.workspace.id}/overview`}>继续课题 <RightOutlined /></Link></div></Card></Col>)}
          </Row>
        </>
      )}
      {loading && <Alert type="info" showIcon message="正在加载最近课题和待处理事项…" style={{ marginTop: 16 }} />}
    </div>
  );
}
