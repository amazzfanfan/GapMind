import { Card, Empty, List, Tag, Typography } from "antd";
import {
  ArrowRightOutlined,
  ClockCircleOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { Link } from "react-router-dom";
import type { DiscoverRun, ResearchOpportunity } from "../api/discover";
import type { Task } from "../api/types/domain";
import type { Workspace, WorkspaceReadiness } from "../api/types/workspace";

interface ActiveWorkspacePanelProps {
  workspace: Workspace | null;
  counts: WorkspaceReadiness["counts"] | null;
  pendingTasks: Task[] | null;
  waitingRuns: DiscoverRun[] | null;
  opportunities: ResearchOpportunity[] | null;
  pendingOpportunityCount: number | null;
  loading?: boolean;
}

interface ActivityItem {
  key: string;
  title: string;
  detail: string;
  href: string;
  time: string;
  timestamp: number;
  tone: "ai" | "alert" | "user";
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length > 1) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  return name.trim().slice(0, 2).toUpperCase() || "WS";
}

function relativeTime(value: string): string {
  const elapsed = Math.max(0, Date.now() - new Date(value).getTime());
  const minutes = Math.floor(elapsed / 60_000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  return `${days} 天前`;
}

function activityItems({
  workspace,
  pendingTasks,
  waitingRuns,
  opportunities,
}: Pick<ActiveWorkspacePanelProps, "workspace" | "pendingTasks" | "waitingRuns" | "opportunities">): ActivityItem[] {
  if (!workspace) return [];
  const items: ActivityItem[] = [];
  (pendingTasks ?? []).forEach((task) => {
    items.push({
      key: `task-${task.id}`,
      title: task.status === "failed" ? "后台处理失败，等待检查" : "后台处理正在进行",
      detail: task.task_type || "论文与知识处理",
      href: `/workspaces/${workspace.id}/activity`,
      time: relativeTime(task.created_at),
      timestamp: new Date(task.created_at).getTime(),
      tone: task.status === "failed" ? "alert" : "ai",
    });
  });
  (waitingRuns ?? []).forEach((run) => {
    items.push({
      key: `run-${run.id}`,
      title: "Discover 运行等待继续",
      detail: run.stage || "研究机会发现",
      href: `/workspaces/${workspace.id}/discover?run=${run.id}`,
      time: relativeTime(run.updated_at),
      timestamp: new Date(run.updated_at).getTime(),
      tone: "alert",
    });
  });
  (opportunities ?? []).forEach((opportunity) => {
    items.push({
      key: `opportunity-${opportunity.id}`,
      title: opportunity.title,
      detail: "研究机会等待人工判断",
      href: `/workspaces/${workspace.id}/discover?opportunity=${opportunity.id}`,
      time: relativeTime(opportunity.updated_at),
      timestamp: new Date(opportunity.updated_at).getTime(),
      tone: "ai",
    });
  });
  return items.sort((a, b) => b.timestamp - a.timestamp).slice(0, 3);
}

function Metric({ label, value, detail, href, tone = "default" }: {
  label: string;
  value: number | string;
  detail: string;
  href: string;
  tone?: "default" | "alert";
}) {
  return (
    <Link to={href} className="gm-active-workspace-metric">
      <span className="gm-active-workspace-metric-label">{label}</span>
      <strong>{value}</strong>
      <span className={tone === "alert" ? "is-alert" : ""}>{detail}</span>
    </Link>
  );
}

export default function ActiveWorkspacePanel({
  workspace,
  counts,
  pendingTasks,
  waitingRuns,
  opportunities,
  pendingOpportunityCount,
  loading = false,
}: ActiveWorkspacePanelProps) {
  if (loading || !workspace) {
    return <Card className="gm-active-workspace-panel" loading={loading}>
      {!loading && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有可展示的活跃课题" />}
    </Card>;
  }

  const pendingKnowledge = counts?.pending_knowledge ?? 0;
  const pendingOpportunities = counts?.pending_opportunities ?? pendingOpportunityCount ?? 0;
  const reviewTotal = pendingKnowledge + pendingOpportunities;
  const activities = activityItems({ workspace, pendingTasks, waitingRuns, opportunities });

  return (
    <section className="gm-active-workspace-panel" aria-labelledby="active-workspace-title">
      <div className="gm-active-workspace-header">
        <div>
          <span className="gm-panel-kicker"><FolderOpenOutlined /> ACTIVE WORKSPACE</span>
          <Typography.Title id="active-workspace-title" level={4}>当前活跃课题</Typography.Title>
        </div>
        <Link className="gm-panel-link" to="/workspaces">全部课题 <ArrowRightOutlined /></Link>
      </div>

      <div className="gm-active-workspace-identity">
        <span className="gm-active-workspace-avatar">{initials(workspace.name)}</span>
        <div className="gm-active-workspace-name-wrap">
          <div className="gm-active-workspace-name">
            <Link to={`/workspaces/${workspace.id}/overview`}>{workspace.name}</Link>
            <Tag color="success">Active</Tag>
          </div>
          <Typography.Text type="secondary">
            {workspace.topic || workspace.description || "还没有填写研究主题"}
          </Typography.Text>
        </div>
        <span className="gm-active-workspace-updated"><ClockCircleOutlined /> 最近更新 {relativeTime(workspace.updated_at)}</span>
      </div>

      <div className="gm-active-workspace-metrics">
        <Metric
          label="PAPERS"
          value={counts?.papers ?? "—"}
          detail={counts ? `${counts.papers_with_pdf} 篇已有全文` : "数据暂不可用"}
          href={`/workspaces/${workspace.id}/papers`}
        />
        <Metric
          label="DISCOVER RUNS"
          value={counts?.runs ?? "—"}
          detail={counts?.pending_runs ? `${counts.pending_runs} 项等待继续` : "暂无等待运行"}
          tone={counts?.pending_runs ? "alert" : "default"}
          href={`/workspaces/${workspace.id}/discover`}
        />
        <Metric
          label="RESEARCH PLANS"
          value={counts?.research_plans ?? "—"}
          detail="研究计划资产"
          href={`/workspaces/${workspace.id}/plans`}
        />
        <Metric
          label="REVIEW QUEUE"
          value={counts ? reviewTotal : "—"}
          detail={counts ? `${pendingKnowledge} 条知识 · ${pendingOpportunities} 个机会` : "数据暂不可用"}
          tone={reviewTotal > 0 ? "alert" : "default"}
          href={`/workspaces/${workspace.id}/overview`}
        />
      </div>

      <div className="gm-active-workspace-activity">
        <div className="gm-active-workspace-activity-title"><ThunderboltOutlined /> 最近 AI 活动</div>
        {activities.length > 0 ? (
          <List
            size="small"
            dataSource={activities}
            renderItem={(activity) => (
              <List.Item className="gm-active-workspace-activity-item">
                <span className={`gm-activity-dot is-${activity.tone}`} />
                <Link to={activity.href} className="gm-active-workspace-activity-copy">
                  <strong>{activity.title}</strong>
                  <span>{activity.detail}</span>
                </Link>
                <Typography.Text type="secondary">{activity.time}</Typography.Text>
              </List.Item>
            )}
          />
        ) : (
          <div className="gm-active-workspace-empty-activity">
            <FileTextOutlined /> 暂无待处理活动，进入课题继续收集证据。
          </div>
        )}
      </div>
    </section>
  );
}
