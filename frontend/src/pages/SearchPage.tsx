import { Typography } from "antd";
import SemanticPaperSearch from "../components/SemanticPaperSearch";

const { Title, Paragraph } = Typography;

export default function SearchPage() {
  return (
    <div>
      <Title level={3}>Paper Search</Title>
      <Paragraph type="secondary">
        Search Semantic Scholar, review papers, and import open-access research into a workspace.
      </Paragraph>
      <SemanticPaperSearch />
    </div>
  );
}
