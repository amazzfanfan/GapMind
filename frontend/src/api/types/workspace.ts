// Workspace type aliases — all re-exports of the auto-generated OpenAPI
// schemas. Run `npm run gen:api` after touching backend Pydantic models
// to keep these in sync.
//
// Do NOT add hand-written fields here. If a field is missing from the
// backend, add it to the Pydantic schema and regenerate.

import type { components } from "./api.gen";

export type Workspace = components["schemas"]["WorkspaceRead"];
export type WorkspaceCreate = components["schemas"]["WorkspaceCreate"];
export type WorkspaceUpdate = components["schemas"]["WorkspaceUpdate"];
export type WorkspaceListResponse = components["schemas"]["WorkspaceListResponse"];

export interface WorkspaceListParams {
  include_archived?: boolean;
  limit?: number;
  offset?: number;
}