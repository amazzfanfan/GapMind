import SemanticPaperSearch from "../components/SemanticPaperSearch";
import PageHeader from "../components/common/PageHeader";

export default function SearchPage() {
  return (
    <div>
      <PageHeader eyebrow="跨课题检索" title="论文检索" description="在 Semantic Scholar 中搜索论文。全局导入时请选择目标课题；进入具体课题后可直接绑定当前课题。" />
      <SemanticPaperSearch />
    </div>
  );
}
