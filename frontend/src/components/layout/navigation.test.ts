import { describe, expect, it } from "vitest";
import { selectedGlobalKey, selectedWorkspaceKey, workspaceNavigationPath } from "./navigation";

describe("navigation helpers", () => {
  it("keeps global navigation selected for nested routes", () => {
    expect(selectedGlobalKey("/workspaces/ws-1/discover/runs/run-1")).toBe("/discover");
    expect(selectedGlobalKey("/search?query=gnn")).toBe("/search");
    expect(selectedGlobalKey("/chat/conversation-1")).toBe("/chat");
    expect(selectedGlobalKey("/")).toBe("/");
  });

  it("selects lifecycle entries for workspace and assistant routes", () => {
    expect(selectedGlobalKey("/workspaces/ws-1/knowledge")).toBe("/knowledge");
    expect(selectedGlobalKey("/workspaces/ws-1/plans")).toBe("/plan");
    expect(selectedGlobalKey("/workspaces/ws-1/assistant", "?mode=code_generation")).toBe("/execute");
    expect(selectedGlobalKey("/chat/new", "?mode=respond")).toBe("/respond");
  });

  it("keeps workspace navigation selected for graph and discover details", () => {
    expect(selectedWorkspaceKey("/workspaces/ws-1/assistant/conversation-1")).toBe("assistant");
    expect(selectedWorkspaceKey("/workspaces/ws-1/knowledge/graph")).toBe("knowledge");
    expect(selectedWorkspaceKey("/workspaces/ws-1/discover/opportunities/op-1")).toBe("discover");
    expect(selectedWorkspaceKey("/workspaces/ws-1/settings")).toBe("settings");
  });

  it("provides compatibility-safe workspace destinations", () => {
    expect(workspaceNavigationPath("ws-1", "overview")).toBe("/workspaces/ws-1/overview");
    expect(workspaceNavigationPath("ws-1", "papers")).toBe("/workspaces/ws-1/papers");
    expect(workspaceNavigationPath("ws-1", "assistant")).toBe("/workspaces/ws-1/assistant");
    expect(workspaceNavigationPath("ws-1", "plans")).toBe("/workspaces/ws-1/plans");
    expect(selectedWorkspaceKey("/workspaces/ws-1/plans")).toBe("plans");
  });
});
