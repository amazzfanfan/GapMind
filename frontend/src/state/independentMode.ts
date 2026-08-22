/** System-owned workspace backing W7 standalone conversations. */
export const INDEPENDENT_WORKSPACE_NAME = "__independent__";

export function isIndependentWorkspaceName(name?: string): boolean {
  return name === INDEPENDENT_WORKSPACE_NAME;
}
