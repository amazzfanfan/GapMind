import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import ChatSources from "./ChatSources";

describe("ChatSources", () => {
  it("keeps plan, paper, report, and code draft visibly separate", () => {
    const html = renderToStaticMarkup(<ChatSources sources={[
      { marker: "P1", source_type: "plan", source_id: "p1", label: "已确认研究计划", title: "计划 A", status: "confirmed", detail: null },
      { marker: "E1", source_type: "paper", source_id: "paper-1", label: "工作区论文", title: "ProtGNN", status: "indexed", detail: null },
      { marker: "D1", source_type: "report", source_id: "report-1", label: "已确认报告", title: "deep_research_report.md", status: "confirmed", detail: null },
      { marker: "C1", source_type: "code_draft", source_id: "code-1", label: "代码草案，未运行验证", title: "train.py", status: "not_run", detail: null },
    ]} />);

    expect(html).toContain("[P1]");
    expect(html).toContain("[E1]");
    expect(html).toContain("[D1]");
    expect(html).toContain("[C1]");
    expect(html).toContain("代码草案，未运行验证");
    expect(html).toContain("本次回答使用的来源（4）");
  });

  it("renders no context panel when no sources were used", () => {
    expect(renderToStaticMarkup(<ChatSources sources={[]} />)).toBe("");
  });
});
