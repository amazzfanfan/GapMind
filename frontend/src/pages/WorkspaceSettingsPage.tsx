import { useState } from "react";
import { App, Button, Card, Form, Input, Space, Tag, Typography } from "antd";
import { SaveOutlined } from "@ant-design/icons";
import workspaceApi from "../api/workspace";
import type { Workspace } from "../api/types/workspace";
import PageHeader from "../components/common/PageHeader";
import TechnicalDetails from "../components/common/TechnicalDetails";
import { useWorkspaceLayout } from "../components/layout/WorkspaceLayout";

const { TextArea } = Input;

interface FormValues { name: string; description?: string; topic?: string; keywords?: string; goals?: string; constraints?: string; active_questions?: string; }

function valuesFor(workspace: Workspace): FormValues {
  return { name: workspace.name, description: workspace.description ?? "", topic: workspace.topic ?? "", keywords: workspace.keywords.join(", "), goals: workspace.goals ?? "", constraints: workspace.constraints ?? "", active_questions: workspace.active_questions.join("\n") };
}

export default function WorkspaceSettingsPage() {
  const { workspace, reloadWorkspace } = useWorkspaceLayout();
  const { message } = App.useApp();
  const [form] = Form.useForm<FormValues>();
  const [saving, setSaving] = useState(false);

  const save = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      await workspaceApi.update(workspace.id, {
        name: values.name,
        description: values.description || undefined,
        topic: values.topic || undefined,
        goals: values.goals || undefined,
        constraints: values.constraints || undefined,
        keywords: values.keywords ? values.keywords.split(/[\n,]/).map((value) => value.trim()).filter(Boolean) : [],
        active_questions: values.active_questions ? values.active_questions.split(/\n/).map((value) => value.trim()).filter(Boolean) : [],
      });
      await reloadWorkspace();
      message.success("课题设置已保存");
    } catch (error) {
      message.error(`保存失败：${(error as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <PageHeader eyebrow="课题配置" title="设置" description="调整研究主题、目标、关键词和约束。这些信息会作为文献检索与 Discover 的上下文。" />
      <Card>
        <Form form={form} layout="vertical" initialValues={valuesFor(workspace)}>
          <Form.Item name="name" label="课题名称" rules={[{ required: true, message: "请输入课题名称" }]}><Input /></Form.Item>
          <Form.Item name="topic" label="研究主题"><Input /></Form.Item>
          <Form.Item name="keywords" label="关键词" extra="使用逗号或换行分隔"><Input /></Form.Item>
          <Form.Item name="goals" label="研究目标"><TextArea rows={3} /></Form.Item>
          <Form.Item name="constraints" label="研究约束"><TextArea rows={3} /></Form.Item>
          <Form.Item name="active_questions" label="当前研究问题" extra="每行一个问题"><TextArea rows={4} /></Form.Item>
          <Form.Item name="description" label="课题描述"><TextArea rows={3} /></Form.Item>
          <Button type="primary" icon={<SaveOutlined />} onClick={() => void save()} loading={saving}>保存设置</Button>
        </Form>
      </Card>
      <Card title="课题状态" style={{ marginTop: 20 }}>
        <Space wrap><Typography.Text>当前状态：</Typography.Text><Tag color={workspace.is_archived ? "default" : "green"}>{workspace.is_archived ? "已归档" : "进行中"}</Tag><Typography.Text type="secondary">归档和删除仍由课题空间列表管理。</Typography.Text></Space>
        <TechnicalDetails><>{`workspace_id: ${workspace.id} · created_at: ${workspace.created_at} · updated_at: ${workspace.updated_at}`}</></TechnicalDetails>
      </Card>
    </div>
  );
}
