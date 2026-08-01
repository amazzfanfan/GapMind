import { useCallback, useEffect, useState } from "react";
import { App, Card, Col, Row, Statistic, Typography } from "antd";
import taskApi from "../api/task";
import timelineApi from "../api/timeline";
import type { Task, TimelineEvent } from "../api/types/domain";
import TasksSection from "../components/TasksSection";
import TimelineSection from "../components/TimelineSection";
import PageHeader from "../components/common/PageHeader";
import { useWorkspaceLayout } from "../components/layout/WorkspaceLayout";

export default function WorkspaceActivityPage() {
  const { workspace } = useWorkspaceLayout();
  const { message } = App.useApp();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [taskResult, timelineResult] = await Promise.allSettled([
      taskApi.list(workspace.id, { limit: 100 }),
      timelineApi.list(workspace.id, { limit: 100 }),
    ]);
    if (taskResult.status === "fulfilled") setTasks(taskResult.value.items);
    else message.error("处理任务加载失败");
    if (timelineResult.status === "fulfilled") setTimeline(timelineResult.value.items);
    else message.error("课题动态加载失败");
    setLoading(false);
  }, [message, workspace.id]);

  useEffect(() => { void load(); }, [load]);

  const active = tasks.filter((task) => ["queued", "running"].includes(task.status)).length;
  const waiting = tasks.filter((task) => task.status === "waiting_for_user").length;
  const failed = tasks.filter((task) => task.status === "failed").length;
  const hasActive = tasks.some((task) => ["queued", "running", "waiting_for_user"].includes(task.status));

  useEffect(() => {
    if (!hasActive) return;
    const timer = window.setInterval(() => { void load(); }, 2500);
    return () => window.clearInterval(timer);
  }, [hasActive, load]);

  return (
    <div>
      <PageHeader eyebrow="课题活动" title="动态与处理中心" description="动态记录研究进展；处理中心展示论文解析、知识提取和 Discover 等后台任务。" />
      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={8}><Card><Statistic title="处理中" value={active} suffix="项" /></Card></Col>
        <Col xs={8}><Card><Statistic title="需要你处理" value={waiting} suffix="项" /></Card></Col>
        <Col xs={8}><Card><Statistic title="失败" value={failed} suffix="项" /></Card></Col>
      </Row>
      <Card title="处理中心" style={{ marginBottom: 20 }}>
        <TasksSection tasks={tasks} loading={loading} onChanged={load} />
      </Card>
      <Card title="课题动态">
        <TimelineSection events={timeline} loading={loading} />
      </Card>
      {!loading && !tasks.length && !timeline.length && <Typography.Text type="secondary">完成一次文献导入或 Discover 后，这里会出现处理记录。</Typography.Text>}
    </div>
  );
}
