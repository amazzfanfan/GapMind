import { describe, expect, it } from "vitest";
import {
  INDEPENDENT_WORKSPACE_NAME,
  isIndependentWorkspaceName,
} from "./independentMode";

describe("independent mode identity", () => {
  it("recognizes only the system workspace name", () => {
    expect(isIndependentWorkspaceName(INDEPENDENT_WORKSPACE_NAME)).toBe(true);
    expect(isIndependentWorkspaceName("GNN interpretability")).toBe(false);
    expect(isIndependentWorkspaceName()).toBe(false);
  });
});
