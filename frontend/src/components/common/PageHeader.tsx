import { Space, Typography } from "antd";
import type { ReactNode } from "react";

const { Title, Paragraph } = Typography;

export default function PageHeader({
  eyebrow,
  title,
  description,
  extra,
}: {
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  extra?: ReactNode;
}) {
  return (
    <div className="gm-page-header">
      <div>
        {eyebrow && <Typography.Text className="gm-eyebrow">{eyebrow}</Typography.Text>}
        <Title level={2} style={{ margin: 0 }}>{title}</Title>
        {description && <Paragraph type="secondary" style={{ margin: "6px 0 0" }}>{description}</Paragraph>}
      </div>
      {extra && <Space wrap>{extra}</Space>}
    </div>
  );
}
