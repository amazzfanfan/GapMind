import { describe, expect, it } from "vitest";
import type { KnowledgeGraphEdge, KnowledgeGraphNode } from "../../api/types/knowledge";
import { branchGraph, mergeGraph, projectGraph } from "./graphUtils";

function node(id: string, type: string, nodeKind = "knowledge"): KnowledgeGraphNode {
  return {
    id, label: id, type, node_kind: nodeKind, workspace_id: "ws",
    confidence: 0.9, status: "extracted_candidate", content: {},
    importance_score: 0.8, relation_count: 0, evidence_count: 0, paper_count: 0,
  };
}

function edge(id: string, source: string, target: string): KnowledgeGraphEdge {
  return { id, source, target, relation_type: "related_to", confidence: 0.8, payload: {} };
}

describe("knowledge graph utilities", () => {
  const graph = {
    nodes: [
      node("paper", "paper", "paper"),
      node("method", "method"),
      node("claim", "claim"),
      node("mention", "paper_mention", "paper_mention"),
    ],
    edges: [edge("pm", "paper", "method"), edge("pc", "paper", "claim"), edge("cm", "claim", "mention")],
  };

  it("projects the three views without dangling edges", () => {
    expect(projectGraph(graph, "landscape").nodes.map((item) => item.id)).toEqual(["paper", "method"]);
    expect(projectGraph(graph, "claims").nodes.map((item) => item.id)).toEqual(["paper", "claim"]);
    expect(projectGraph(graph, "evidence").nodes).toHaveLength(4);
    for (const mode of ["landscape", "claims", "evidence"] as const) {
      const projected = projectGraph(graph, mode);
      const ids = new Set(projected.nodes.map((item) => item.id));
      expect(projected.edges.every((item) => ids.has(item.source) && ids.has(item.target))).toBe(true);
    }
  });

  it("merges appended batches and neighbor expansions by id", () => {
    const merged = mergeGraph(
      { nodes: [node("a", "method")], edges: [] },
      { nodes: [node("a", "method"), node("b", "task")], edges: [edge("ab", "a", "b")] },
    );
    expect(merged.nodes.map((item) => item.id)).toEqual(["a", "b"]);
    expect(merged.edges.map((item) => item.id)).toEqual(["ab"]);
  });

  it("limits a branch to the selected node and its one-hop neighbors", () => {
    const result = branchGraph(
      { nodes: [node("a", "claim"), node("b", "claim"), node("c", "claim")], edges: [edge("ab", "a", "b")] },
      "a",
    );
    expect(result.nodes.map((item) => item.id)).toEqual(["a", "b"]);
  });
});
