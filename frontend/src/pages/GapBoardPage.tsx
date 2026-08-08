import { useCallback, useEffect, useMemo, useState } from "react";
import { App, Alert, Button, Card, Empty, Popconfirm, Space, Statistic, Table, Tag, Typography } from "antd";
import { ExperimentOutlined, ReloadOutlined, RobotOutlined } from "@ant-design/icons";
import { useNavigate, useParams } from "react-router-dom";
import gapApi, { type GapAnnotation, type GapBoard, type GapBoardCell } from "../api/gap";
import paperApi from "../api/paper";

const { Paragraph, Text, Title } = Typography;

function errorMessage(error: unknown): string {
  const value = error as {
    response?: { status?: number; data?: { detail?: string | { message?: string } } };
    message?: string;
  };
  const detail = value.response?.data?.detail;
  if (typeof detail === "string") return detail;
  return detail?.message || value.message || "请求失败";
}

const candidatePresentation: Record<
  GapBoardCell["candidate_tier"],
  { label: string; color: string }
> = {
  covered: { label: "已有方法解决", color: "green" },
  explicit_limitation: { label: "明确剩余局限", color: "orange" },
  same_paper_unlinked: { label: "同篇共现待核验", color: "gold" },
  cross_paper_transfer: { label: "跨论文迁移候选", color: "blue" },
  corpus_only: { label: "语料库未覆盖（低证据）", color: "default" },
};

export default function GapBoardPage() {
  const { id: workspaceId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [board, setBoard] = useState<GapBoard | null>(null);
  const [annotations, setAnnotations] = useState<GapAnnotation[]>([]);
  const [loading, setLoading] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);
  const [discovering, setDiscovering] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!workspaceId) return;
    setLoading(true);
    try {
      const annotationResponse = await gapApi.listAnnotations(workspaceId);
      setAnnotations(annotationResponse.items);
      try {
        setBoard(await gapApi.getBoard(workspaceId));
      } catch (error) {
        const status = (error as { response?: { status?: number } }).response?.status;
        if (status === 404) setBoard(null);
        else throw error;
      }
    } catch (error) {
      message.error(`加载研究空白棋盘失败：${errorMessage(error)}`);
    } finally {
      setLoading(false);
    }
  }, [message, workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const runExtraction = async () => {
    if (!workspaceId) return;
    setExtracting(true);
    try {
      const allPapers: Awaited<ReturnType<typeof paperApi.list>>["items"] = [];
      let offset = 0;
      let total = 1;
      while (offset < total) {
        const page = await paperApi.list(workspaceId, { limit: 100, offset });
        allPapers.push(...page.items);
        total = page.total;
        offset += page.items.length;
        if (!page.items.length) break;
      }
      const eligible = allPapers
        .filter((paper) => paper.parse_status === "parsed" && paper.parsed_markdown_artifact_id)
        .map((paper) => paper.id);
      if (!eligible.length) {
        message.warning("当前没有已完成 Markdown 解析的论文。");
        return;
      }
      let submitted = 0;
      for (let index = 0; index < eligible.length; index += 200) {
        const response = await gapApi.extract(workspaceId, eligible.slice(index, index + 200));
        submitted += response.tasks.length;
      }
      message.success(`已提交 ${submitted} 篇论文。完成后请刷新并重建棋盘。`);
    } catch (error) {
      message.error(`提交专项抽取失败：${errorMessage(error)}`);
    } finally {
      setExtracting(false);
    }
  };

  const rebuild = async () => {
    if (!workspaceId) return;
    setRebuilding(true);
    try {
      const next = await gapApi.rebuildBoard(workspaceId);
      setBoard(next);
      message.success(`棋盘 v${next.version} 已生成。`);
    } catch (error) {
      message.error(`重建棋盘失败：${errorMessage(error)}`);
    } finally {
      setRebuilding(false);
    }
  };

  const verifyCandidate = async (cell: GapBoardCell, exploratory = false) => {
    if (!workspaceId) return;
    const key = `${cell.method_concept_id}:${cell.problem_concept_id}`;
    setDiscovering(key);
    try {
      const result = await gapApi.discoverCandidate(
        workspaceId,
        cell.method_concept_id,
        cell.problem_concept_id,
        exploratory,
      );
      message.success(
        exploratory
          ? "已发起探索性核验；系统会先检查机制兼容性与已有工作，不会直接认定研究空白。"
          : "已交给 Discover 进行相似工作、外部论文与反证核验。",
      );
      navigate(`/workspaces/${workspaceId}/discover?run=${result.run_id}`);
    } catch (error) {
      message.error(`启动候选核验失败：${errorMessage(error)}`);
    } finally {
      setDiscovering(null);
    }
  };

  const cellIndex = useMemo(
    () =>
      new Map(
        (board?.cells || []).map((cell) => [
          `${cell.method_concept_id}:${cell.problem_concept_id}`,
          cell,
        ]),
      ),
    [board],
  );

  const columns = useMemo(() => {
    if (!board) return [];
    return [
      {
        title: "方法策略（纵轴）",
        dataIndex: "label",
        key: "method",
        fixed: "left" as const,
        width: 220,
        render: (label: string, method: GapBoard["method_axes"][number]) => (
          <Space direction="vertical" size={0}>
            <Text strong>{label}</Text>
            <Text type="secondary">{method.paper_count} 篇论文</Text>
          </Space>
        ),
      },
      ...board.problem_axes.map((problem) => ({
        title: (
          <Space direction="vertical" size={0}>
            <Text strong>{problem.label}</Text>
            <Text type="secondary">{problem.paper_count} 篇</Text>
          </Space>
        ),
        key: problem.concept_id,
        width: 210,
        render: (_: unknown, method: GapBoard["method_axes"][number]) => {
          const cell = cellIndex.get(`${method.concept_id}:${problem.concept_id}`);
          if (!cell) return <Text type="secondary">—</Text>;
          if (cell.addressed) {
            return (
              <Space direction="vertical" size={4}>
                <Tag color="green">已有方法解决</Tag>
                <Text type="secondary">{cell.addressed_paper_ids.length} 篇支持</Text>
              </Space>
            );
          }
          const key = `${cell.method_concept_id}:${cell.problem_concept_id}`;
          const presentation = candidatePresentation[cell.candidate_tier] || candidatePresentation.corpus_only;
          return (
            <Space direction="vertical" size={4}>
              <Tag color={presentation.color}>{presentation.label}</Tag>
              <Text type="secondary">核验优先级 {cell.candidate_score.toFixed(2)}</Text>
              {cell.candidate_reasons[0] ? (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {cell.candidate_reasons[0]}
                </Text>
              ) : null}
              {cell.eligible_for_discovery ? (
                <Button
                  size="small"
                  type="link"
                  loading={discovering === key}
                  onClick={() => void verifyCandidate(cell)}
                >
                  交给 Discover 核验
                </Button>
              ) : (
                <Popconfirm
                  title="发起低证据探索性核验？"
                  description="该组合目前仅来自横纵轴配对。Discover 会检索机制兼容性、相似工作和反证，但不会把空格直接当作研究空白。"
                  okText="继续核验"
                  cancelText="取消"
                  onConfirm={() => void verifyCandidate(cell, true)}
                >
                  <Button size="small" type="link" loading={discovering === key}>
                    探索性核验
                  </Button>
                </Popconfirm>
              )}
            </Space>
          );
        },
      })),
    ];
  }, [board, cellIndex, discovering]);

  if (!workspaceId) return <Empty description="工作区不存在" />;
  const validCount = annotations.filter((item) => item.status === "valid").length;
  const invalidCount = annotations.filter((item) => item.status === "invalid").length;
  const uncoveredCount = board?.cells.filter((item) => !item.addressed).length || 0;

  return (
    <Space direction="vertical" size={18} style={{ width: "100%" }}>
      <Space wrap style={{ width: "100%", justifyContent: "space-between" }}>
        <div>
          <Title level={2} style={{ margin: 0 }}>研究空白棋盘</Title>
          <Paragraph type="secondary" style={{ margin: "4px 0 0" }}>
            纵轴为跨论文归一化的方法策略，横轴为问题标签；空格仅是待核验候选，不是研究空白结论。
          </Paragraph>
        </div>
        <Space wrap>
          <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>
            刷新
          </Button>
          <Button icon={<RobotOutlined />} loading={extracting} onClick={() => void runExtraction()}>
            抽取已解析论文
          </Button>
          <Button type="primary" icon={<ExperimentOutlined />} loading={rebuilding} onClick={() => void rebuild()}>
            重建棋盘
          </Button>
        </Space>
      </Space>

      <Alert
        type="warning"
        showIcon
        message="棋盘空格不等于真实研究空白，优先级也不是成功概率"
        description="系统保留全部未覆盖格用于观察，但只有明确局限、同篇共现未连接，或方法族与问题族均获得多篇论文支持的格子会进入推荐核验。之后仍须经过相似工作、外部论文、反证与 Evidence Gate。"
      />

      <Space wrap>
        <Card size="small"><Statistic title="有效专项标注" value={validCount} /></Card>
        <Card size="small"><Statistic title="隔离的无效标注" value={invalidCount} /></Card>
        <Card size="small"><Statistic title="棋盘版本" value={board?.version || 0} /></Card>
        <Card size="small"><Statistic title="全部未覆盖格" value={uncoveredCount} /></Card>
        <Card size="small"><Statistic title="推荐核验候选格" value={board?.candidate_count || 0} /></Card>
      </Space>

      <Card title="方法 × 问题" loading={loading}>
        {!board || !board.method_axes.length || !board.problem_axes.length ? (
          <Empty description="先完成专项抽取，再重建棋盘。" />
        ) : (
          <Table
            rowKey="concept_id"
            dataSource={board.method_axes}
            columns={columns}
            pagination={false}
            bordered
            scroll={{ x: Math.max(900, 220 + board.problem_axes.length * 210) }}
          />
        )}
      </Card>
    </Space>
  );
}
