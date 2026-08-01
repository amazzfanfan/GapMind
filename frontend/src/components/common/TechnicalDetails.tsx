import { Collapse, Typography } from "antd";
import type { ReactNode } from "react";

export default function TechnicalDetails({
  title = "技术详情",
  children,
}: {
  title?: string;
  children: ReactNode;
}) {
  return (
    <Collapse
      ghost
      items={[{ key: "technical", label: title, children: <Typography.Text code>{children}</Typography.Text> }]}
    />
  );
}
