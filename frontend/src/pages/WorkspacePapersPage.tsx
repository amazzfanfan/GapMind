import { useCallback, useEffect, useState } from "react";
import { App } from "antd";
import paperApi from "../api/paper";
import type { Paper } from "../api/types/domain";
import PapersSection from "../components/PapersSection";
import SemanticPaperSearch from "../components/SemanticPaperSearch";
import PageHeader from "../components/common/PageHeader";
import { useWorkspaceLayout } from "../components/layout/WorkspaceLayout";

export default function WorkspacePapersPage() {
  const { workspace } = useWorkspaceLayout();
  const { message } = App.useApp();
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setPapers((await paperApi.list(workspace.id, { limit: 100 })).items);
    } catch (error) {
      message.error(`文献加载失败：${(error as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [message, workspace.id]);

  useEffect(() => { void load(); }, [load]);

  return (
    <div>
      <PageHeader eyebrow="证据库" title="文献" description="搜索、导入和解析属于这个课题的论文。解析完成后，全文才可以用于知识提取和 Discover 证据验证。" />
      <SemanticPaperSearch workspaceId={workspace.id} />
      <div style={{ marginTop: 20 }}><PapersSection workspaceId={workspace.id} papers={papers} loading={loading} onChanged={load} /></div>
    </div>
  );
}
