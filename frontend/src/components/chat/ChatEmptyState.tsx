import { Card, Space, Typography } from "antd";

const examples = ["帮我梳理这个研究问题的思路", "解释一下什么是时间图神经网络", "帮我比较两种实验方案", "把下面这段研究描述改得更清楚"];

export default function ChatEmptyState({ onExample }: { onExample: (value: string) => void }) {
  return <div className="gm-chat-empty-state"><Typography.Title level={3}>有什么研究问题想一起梳理？</Typography.Title><Typography.Paragraph type="secondary">这里是普通 AI 对话，回答来自已配置的 DeepSeek，不会自动检索论文或知识库。</Typography.Paragraph><Space wrap className="gm-chat-examples">{examples.map((example) => <Card hoverable size="small" key={example} onClick={() => onExample(example)}>{example}</Card>)}</Space></div>;
}
