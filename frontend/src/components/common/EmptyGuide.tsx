import { Button, Empty } from "antd";
import type { ReactNode } from "react";

export default function EmptyGuide({
  description,
  actionText,
  onAction,
  actionIcon,
  children,
}: {
  description: ReactNode;
  actionText?: string;
  onAction?: () => void;
  actionIcon?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <Empty description={description}>
      {children}
      {actionText && onAction && (
        <Button type="primary" icon={actionIcon} onClick={onAction}>
          {actionText}
        </Button>
      )}
    </Empty>
  );
}
