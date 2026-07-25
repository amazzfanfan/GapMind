import { useState } from "react";
import { Alert, Button, Card, Empty, Modal, Space, Table, Tag, Tooltip, Typography } from "antd";
import { CopyOutlined, ReloadOutlined } from "@ant-design/icons";
import type { ExtractionRejection, Task } from "../api/types/domain";
import knowledgeApi from "../api/knowledge";
import taskApi from "../api/task";

const { Text } = Typography;

interface Props {
  tasks: Task[];
  loading: boolean;
  onChanged: () => void;
}

const STATUS_COLOR: Record<Task["status"], string> = {
  queued: "default",
  running: "processing",
  waiting_for_user: "warning",
  succeeded: "success",
  failed: "error",
  // cancel_requested is treated as terminal in the UI - MVP worker doesn't
  // monitor cancel signals, so this state never transitions to "cancelled".
  // Display it as cancelled (grey) to match user expectation. The raw status
  // is still in the DB for audit. See progress_and_roadmap.md for the
  // follow-up: implement real worker cancel monitoring in Phase 4.
  cancel_requested: "default",
  cancelled: "default",
};

// Map raw status to display label. cancel_requested is shown as "cancelled"
// since from the user's perspective the task is no longer active.
const STATUS_LABEL: Record<Task["status"], string> = {
  queued: "queued",
  running: "running",
  waiting_for_user: "waiting",
  succeeded: "succeeded",
  failed: "failed",
  cancel_requested: "cancelled",
  cancelled: "cancelled",
};

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
  const [rejectionTask, setRejectionTask] = useState<Task | null>(null);
  const [rejections, setRejections] = useState<ExtractionRejection[]>([]);
  const [rejectionTotal, setRejectionTotal] = useState(0);
  const [rejectionPage, setRejectionPage] = useState(1);
  const [rejectionsLoading, setRejectionsLoading] = useState(false);
  const [rejectionsError, setRejectionsError] = useState<string | null>(null);

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
    try {
      await taskApi.cancel(taskId);
      onChanged();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: { message?: string } } } }).response?.data?.detail;
      window.alert(detail?.message || (err as Error).message);
    }
  };

  const handleRetry = async (taskId: string) => {
    try {
      await taskApi.retry(taskId);
      onChanged();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: { message?: string } } } }).response?.data?.detail;
      window.alert(detail?.message || (err as Error).message);
    }
  };

  return (
    <>
      <Card
      title={
        <Space>
          <span>Tasks</span>
          <Tooltip title="Refresh">
            <Button size="small" icon={<ReloadOutlined />} onClick={onChanged} loading={loading} />
          </Tooltip>
        </Space>
      }
    >
      {tasks.length === 0 && !loading ? (
        <Empty description="No tasks yet. Tasks are created automatically when you upload papers (Phase 2) or run discovery (Phase 5)." />
      ) : (
        <Table<Task>
          rowKey="id"
          dataSource={tasks}
          loading={loading}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          columns={[
            {
              title: "Type",
              dataIndex: "task_type",
              key: "task_type",
              render: (v: string) => <Text code>{v}</Text>,
            },
            {
              title: "Status",
              dataIndex: "status",
              key: "status",
              width: 140,
              render: (s: Task["status"]) => (
                <Tag color={STATUS_COLOR[s]}>{STATUS_LABEL[s]}</Tag>
              ),
            },
            {
              title: "Progress",
              dataIndex: "progress",
              key: "progress",
              width: 100,
              render: (p: number) => `${Math.round(p * 100)}%`,
            },
            {
              title: "Error",
              dataIndex: "error",
              key: "error",
              ellipsis: true,
              render: (e: string | null) =>
                e ? (
                  <Tooltip title={taskErrorSummary(e)}>
                    <Text type="danger" ellipsis>
                      {taskErrorSummary(e)}
                    </Text>
                  </Tooltip>
                ) : (
                  "—"
                ),
            },
            {
              title: "Rejected",
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
                    {count > 0 ? `View (${count})` : "View"}
                  </Button>
                );
              },
            },
            {
              title: "Created",
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
                    <Button size="small" onClick={() => handleCancel(t.id)}>
                      Cancel
                    </Button>
                  );
                }
                if (t.status === "failed") {
                  return (
                    <Button size="small" onClick={() => handleRetry(t.id)}>
                      Retry
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
        title="Extraction rejections"
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
              title: "Kind",
              dataIndex: "rejection_kind",
              width: 90,
              render: (value: string) => <Tag>{value}</Tag>,
            },
            {
              title: "Stage",
              dataIndex: "stage",
              width: 150,
            },
            {
              title: "Object",
              key: "object",
              width: 180,
              render: (_: unknown, item) =>
                item.canonical_name || item.item_type || "Output",
            },
            {
              title: "Reason",
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
                    <summary>Full rejected JSON</summary>
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
                      Copy JSON
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
