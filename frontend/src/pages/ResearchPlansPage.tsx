import { Button, Card, Result } from "antd";
import { BulbOutlined } from "@ant-design/icons";
import { Link } from "react-router-dom";
import { useWorkspaceLayout } from "../components/layout/WorkspaceLayout";

export default function ResearchPlansPage() {
  const { workspace } = useWorkspaceLayout();
  return (
    <Card>
      <Result
        icon={<BulbOutlined />}
        title="研究计划将在确认机会后生成"
        subTitle="当前后端还没有独立的研究计划列表接口。请先在 Discover 中确认一个研究机会，再从机会详情生成计划。"
        extra={<Link to={`/workspaces/${workspace.id}/discover`}><Button type="primary">打开 Discover</Button></Link>}
      />
    </Card>
  );
}
