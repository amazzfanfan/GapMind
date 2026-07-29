import { describe, expect, it } from "vitest";

import { normalizeSemanticScholarPaper } from "./semanticScholar";

describe("normalizeSemanticScholarPaper", () => {
  it("supplies safe defaults for sparse Semantic Scholar results", () => {
    const paper = normalizeSemanticScholarPaper({
      paperId: "s2-paper",
      title: "Sparse result",
    });

    expect(paper.paperId).toBe("s2-paper");
    expect(paper.authors).toEqual([]);
    expect(paper.fieldsOfStudy).toBeNull();
    expect(paper.publicationTypes).toBeNull();
    expect(paper.openAccessPdf).toBeNull();
  });

  it("normalizes malformed author values without throwing", () => {
    const paper = normalizeSemanticScholarPaper({
      paperId: "s2-paper",
      authors: [
        { authorId: null, name: "Ada" },
        null,
      ] as unknown as never[],
    });

    expect(paper.authors).toEqual([{ authorId: null, name: "Ada" }]);
  });
});
