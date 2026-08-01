import { Card, Empty, List, Tag, Typography } from "antd";
import type { TimelineEvent } from "../api/types/domain";

const { Text, Paragraph } = Typography;

interface Props {
  events: TimelineEvent[];
  loading: boolean;
}

const ACTOR_COLOR: Record<string, string> = {
  system: "blue",
  agent: "purple",
  user: "green",
};

function summarize(e: TimelineEvent): string {
  // Human-friendly label for common event types; falls back to event_type.
  const map: Record<string, string> = {
    "paper.created": "添加了文献",
    "paper.uploaded": "上传了文献",
    "paper.updated": "更新了文献",
    "paper.deleted": "删除了文献",
    "task.created": "创建了后台处理",
    "task.running": "后台处理开始",
    "task.succeeded": "后台处理完成",
    "task.failed": "后台处理失败",
    "task.cancelled": "后台处理已取消",
    "task.queued": "后台处理已排队",
  };
  return map[e.event_type] ?? e.event_type;
}

function visiblePayload(e: TimelineEvent): Record<string, unknown> {
  if (e.subject_type !== "task") return e.payload;
  const safe = { ...e.payload };
  delete safe.error;
  delete safe.traceback;
  delete safe.stack;
  return safe;
}

export default function TimelineSection({ events, loading }: Props) {
  return (
    <Card title="课题动态">
      {events.length === 0 && !loading ? (
        <Empty description="还没有课题动态，开始添加文献或运行 Discover 后会自动记录。" />
      ) : (
        <List
          loading={loading}
          dataSource={events}
          renderItem={(e) => {
            const payload = visiblePayload(e);
            return (
              <List.Item>
              <List.Item.Meta
                title={
                  <span>
                    <Text strong>{summarize(e)}</Text>{" "}
                    <Tag color={ACTOR_COLOR[e.actor] ?? "default"}>{e.actor}</Tag>
                    {e.subject_type && <Tag>{e.subject_type}</Tag>}
                  </span>
                }
                description={
                  <span>
                    <Text type="secondary">
                      {new Date(e.created_at).toLocaleString()}
                    </Text>
                    {Object.keys(payload).length > 0 && (
                      <Paragraph
                        type="secondary"
                        style={{ margin: "4px 0 0", fontSize: 12 }}
                      >
                        <code>{JSON.stringify(payload)}</code>
                      </Paragraph>
                    )}
                  </span>
                }
              />
              </List.Item>
            );
          }}
        />
      )}
    </Card>
  );
}
