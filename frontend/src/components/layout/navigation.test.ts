import { describe, expect, it } from "vitest";
import { selectedGlobalKey, selectedWorkspaceKey, workspaceNavigationPath } from "./navigation";

describe("navigation helpers", () => {
  it("keeps global navigation selected for nested routes", () => {
    expect(selectedGlobalKey("/workspaces/ws-1/discover/runs/run-1")).toBe("/workspaces");
    expect(selectedGlobalKey("/search?query=gnn")).toBe("/search");
    expect(selectedGlobalKey("/")).toBe("/");
  });

  it("keeps workspace navigation selected for graph and discover details", () => {
    expect(selectedWorkspaceKey("/workspaces/ws-1/knowledge/graph")).toBe("knowledge");
    expect(selectedWorkspaceKey("/workspaces/ws-1/discover/opportunities/op-1")).toBe("discover");
    expect(selectedWorkspaceKey("/workspaces/ws-1/settings")).toBe("settings");
  });

  it("provides compatibility-safe workspace destinations", () => {
    expect(workspaceNavigationPath("ws-1", "overview")).toBe("/workspaces/ws-1/overview");
    expect(workspaceNavigationPath("ws-1", "papers")).toBe("/workspaces/ws-1/papers");
  });
});
