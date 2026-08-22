import { useState } from "react";
import { Alert, App, Button, Card, Empty, Modal, Space, Table, Tag, Tooltip, Typography } from "antd";
import { CopyOutlined, ReloadOutlined } from "@ant-design/icons";
import type { ExtractionRejection, Task } from "../api/types/domain";
import knowledgeApi from "../api/knowledge";
import taskApi from "../api/task";
import StatusBadge, { taskTypeLabel } from "./common/StatusBadge";
import TechnicalDetails from "./common/TechnicalDetails";

const { Text } = Typography;

interface Props {
  tasks: Task[];
  loading: boolean;
  onChanged: () => void;
}

function taskErrorSummary(error: string): string {
  const firstLine = error.split(/\r?\n/, 1)[0].trim();
  return firstLine.length <= 180
    ? firstLine
    : "Task failed. Check backend logs for technical details.";
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function extractionRunId(task: Task): string | null {
  return (
    stringValue(task.result?.extraction_run_id) ??
    stringValue(task.payload?.extraction_run_id)
  );
}

function rejectedTotal(task: Task): number {
  return numberValue(task.result?.rejected_total);
}

const REJECTION_PAGE_SIZE = 20;

export default function TasksSection({ tasks, loading, onChanged }: Props) {
  const { message } = App.useApp();
  const [rejectionTask, setRejectionTask] = useState<Task | null>(null);
  const [rejections, setRejections] = useState<ExtractionRejection[]>([]);
  const [rejectionTotal, setRejectionTotal] = useState(0);
  const [rejectionPage, setRejectionPage] = useState(1);
  const [rejectionsLoading, setRejectionsLoading] = useState(false);
  const [rejectionsError, setRejectionsError] = useState<string | null>(null);
  const [actionTaskId, setActionTaskId] = useState<string | null>(null);

  const loadRejections = async (task: Task, page = 1) => {
    const runId = extractionRunId(task);
    if (!task.workspace_id || !runId) return;
    setRejectionTask(task);
    setRejectionPage(page);
    setRejectionsLoading(true);
    setRejectionsError(null);
    try {
      const response = await knowledgeApi.listExtractionRejections(
        task.workspace_id,
        runId,
        {
          limit: REJECTION_PAGE_SIZE,
          offset: (page - 1) * REJECTION_PAGE_SIZE,
        }
      );
      setRejections(response.items);
      setRejectionTotal(response.total);
    } catch {
      setRejections([]);
      setRejectionTotal(0);
      setRejectionsError("Failed to load rejection details.");
    } finally {
      setRejectionsLoading(false);
    }
  };

  const handleCancel = async (taskId: string) => {
    setActionTaskId(taskId);
    try {
      await taskApi.cancel(taskId);
      message.success("任务已取消");
      onChanged();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: { message?: string } } } }).response?.data?.detail;
      message.error(detail?.message || (err as Error).message);
    } finally { setActionTaskId(null); }
  };

  const handleRetry = async (taskId: string) => {
    setActionTaskId(taskId);
    try {
      const task = await taskApi.retry(taskId);
      if (task.status === "failed") {
        message.error(task.error || "任务未能重新提交，请检查本地 Worker 与 Redis。");
      } else {
        message.success("任务已重新提交");
      }
      onChanged();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: { message?: string } } } }).response?.data?.detail;
      message.error(detail?.message || (err as Error).message);
    } finally { setActionTaskId(null); }
  };

  return (
    <>
      <Card
      title={
        <Space>
          <span>后台任务</span>
          <Tooltip title="刷新">
            <Button size="small" icon={<ReloadOutlined />} onClick={onChanged} loading={loading} />
          </Tooltip>
        </Space>
      }
    >
      {tasks.length === 0 && !loading ? (
        <Empty description="还没有后台任务。导入论文或启动 Discover 后，处理记录会显示在这里。" />
      ) : (
        <Table<Task>
          rowKey="id"
          dataSource={tasks}
          loading={loading}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          columns={[
            {
              title: "处理内容",
              dataIndex: "task_type",
              key: "task_type",
              render: (v: string) => <Text>{taskTypeLabel(v)}</Text>,
            },
            {
              title: "状态",
              dataIndex: "status",
              key: "status",
              width: 140,
              render: (s: Task["status"]) => <StatusBadge status={s} />,
            },
            {
              title: "进度",
              dataIndex: "progress",
              key: "progress",
              width: 100,
              render: (p: number) => `${Math.round(p * 100)}%`,
            },
            {
              title: "处理反馈",
              dataIndex: "error",
              key: "error",
              ellipsis: true,
              render: (e: string | null) =>
                e ? (
                  <Space direction="vertical" size={0}><Text type="danger">处理失败</Text><TechnicalDetails>{taskErrorSummary(e)}</TechnicalDetails></Space>
                ) : (
                  "—"
                ),
            },
            {
              title: "被拒绝项",
              key: "rejected",
              width: 110,
              render: (_: unknown, task) => {
                const runId = extractionRunId(task);
                const count = rejectedTotal(task);
                if (!runId || (count === 0 && task.status !== "failed")) {
                  return "—";
                }
                return (
                  <Button size="small" onClick={() => loadRejections(task)}>
                    {count > 0 ? `查看（${count}）` : "查看"}
                  </Button>
                );
              },
            },
            {
              title: "更新时间",
              dataIndex: "created_at",
              key: "created_at",
              width: 160,
              render: (v: string) =>
                new Date(v).toLocaleString(undefined, {
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                }),
            },
            {
              title: "",
              key: "actions",
              width: 120,
              render: (_: unknown, t) => {
                if (t.status === "queued" || t.status === "running" || t.status === "waiting_for_user") {
                  return (
                    <Button size="small" loading={actionTaskId === t.id} onClick={() => void handleCancel(t.id)}>
                      取消处理
                    </Button>
                  );
                }
                if (t.status === "failed") {
                  return (
                    <Button size="small" loading={actionTaskId === t.id} onClick={() => void handleRetry(t.id)}>
                      重试
                    </Button>
                  );
                }
                return null;
              },
            },
          ]}
        />
      )}
      </Card>

      <Modal
        title="知识提取未采纳内容"
        open={rejectionTask !== null}
        onCancel={() => setRejectionTask(null)}
        footer={null}
        width={960}
        destroyOnClose
      >
        {rejectionsError && (
          <Alert type="error" showIcon message={rejectionsError} style={{ marginBottom: 12 }} />
        )}
        <Table<ExtractionRejection>
          rowKey="id"
          dataSource={rejections}
          loading={rejectionsLoading}
          size="small"
          pagination={{
            current: rejectionPage,
            pageSize: REJECTION_PAGE_SIZE,
            total: rejectionTotal,
            showSizeChanger: false,
            onChange: (page) => {
              if (rejectionTask) loadRejections(rejectionTask, page);
            },
          }}
          columns={[
            {
              title: "类型",
              dataIndex: "rejection_kind",
              width: 90,
              render: (value: string) => <Tag>{value}</Tag>,
            },
            {
              title: "阶段",
              dataIndex: "stage",
              width: 150,
            },
            {
              title: "Object",
              key: "object",
              width: 180,
              render: (_: unknown, item) =>
                item.canonical_name || item.item_type || "输出",
            },
            {
              title: "原因",
              key: "reason",
              render: (_: unknown, item) => (
                <Space direction="vertical" size={2}>
                  <Text code>{item.reason_code}</Text>
                  <Text type="secondary">{item.reason_detail}</Text>
                  {item.evidence_preview && (
                    <Text type="secondary" italic>
                      {item.evidence_preview}
                    </Text>
                  )}
                  <details>
                    <summary>技术详情</summary>
                    <Button
                      size="small"
                      icon={<CopyOutlined />}
                      style={{ marginTop: 8 }}
                      onClick={() =>
                        navigator.clipboard.writeText(
                          JSON.stringify(item.raw_payload, null, 2)
                        )
                      }
                    >
                      复制 JSON
                    </Button>
                    <pre style={{ maxHeight: 240, overflow: "auto", whiteSpace: "pre-wrap" }}>
                      {JSON.stringify(item.raw_payload, null, 2)}
                    </pre>
                  </details>
                </Space>
              ),
            },
          ]}
        />
      </Modal>
    </>
  );
}
