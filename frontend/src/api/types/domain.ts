// Hand-rolled type aliases for Paper, Task, Timeline, Artifact — re-exported
// from the auto-generated OpenAPI schemas.
//
// Run `npm run gen:api` after touching the corresponding Pydantic models to
// keep these in sync. Do NOT add hand-written fields here; if a field is
// missing, add it to the backend schema and regenerate.
//
// The Omit+Pick overrides relax Pydantic `dict[str, Any]` (rendered as
// `Record<string, never>` by openapi-typescript) to a friendlier
// `Record<string, unknown>` so component code can iterate without casts.

import type { components } from "./api.gen";

type LooseDictField<T, K extends keyof T> = Omit<T, K> & {
  [P in K]: NonNullable<T[P]> | undefined extends T[P]
    ? Record<string, unknown> | undefined
    : Record<string, unknown>;
};

export type Paper = components["schemas"]["PaperRead"];
export type PaperCreate = components["schemas"]["PaperCreate"];
export type PaperUpdate = components["schemas"]["PaperUpdate"];
export type PaperListResponse = components["schemas"]["PaperListResponse"];

export type Artifact = components["schemas"]["ArtifactRead"];

export type Task = components["schemas"]["TaskRead"];
export type TaskListResponse = components["schemas"]["TaskListResponse"];

type _TimelineEventRaw = components["schemas"]["TimelineEventRead"];
export type TimelineEvent = LooseDictField<_TimelineEventRaw, "payload">;
export type TimelineListResponse = components["schemas"]["TimelineListResponse"];

type _ExtractionRejectionRaw = components["schemas"]["ExtractionRejectionRead"];
export type ExtractionRejection = LooseDictField<_ExtractionRejectionRaw, "raw_payload">;
export type ExtractionRejectionListResponse = components["schemas"]["ExtractionRejectionListResponse"];