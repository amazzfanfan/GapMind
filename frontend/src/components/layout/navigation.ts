export const WORKSPACE_NAVIGATION = [
  { key: "overview", label: "概览" },
  { key: "papers", label: "文献" },
  { key: "knowledge", label: "知识" },
  { key: "discover", label: "发现" },
  { key: "plans", label: "研究计划", disabled: true },
  { key: "activity", label: "动态" },
  { key: "settings", label: "设置" },
] as const;

export function selectedGlobalKey(pathname: string): string {
  if (pathname === "/") return "/";
  if (pathname.startsWith("/search")) return "/search";
  if (pathname.startsWith("/workspaces")) return "/workspaces";
  return "/";
}

export function workspaceNavigationPath(workspaceId: string, key: string): string {
  if (key === "overview") return `/workspaces/${workspaceId}/overview`;
  if (key === "knowledge") return `/workspaces/${workspaceId}/knowledge`;
  if (key === "discover") return `/workspaces/${workspaceId}/discover`;
  return `/workspaces/${workspaceId}/${key}`;
}

export function selectedWorkspaceKey(pathname: string): string {
  if (pathname.includes("/knowledge")) return "knowledge";
  if (pathname.includes("/discover")) return "discover";
  const matched = WORKSPACE_NAVIGATION.find((item) => pathname.includes(`/${item.key}`));
  return matched?.key ?? "overview";
}
