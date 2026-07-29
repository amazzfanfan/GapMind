import apiClient from "./client";
import type { Paper } from "./types/domain";

export type SemanticScholarSort =
  | "relevance"
  | "publicationDate:asc"
  | "publicationDate:desc"
  | "citationCount:asc"
  | "citationCount:desc";

export interface SemanticScholarAuthor {
  authorId: string | null;
  name: string | null;
}

export interface SemanticScholarPaper {
  paperId: string;
  corpusId: number | null;
  externalIds: Record<string, unknown> | null;
  url: string | null;
  title: string | null;
  abstract: string | null;
  year: number | null;
  publicationDate: string | null;
  authors: SemanticScholarAuthor[];
  venue: string | null;
  citationCount: number | null;
  referenceCount: number | null;
  influentialCitationCount: number | null;
  isOpenAccess: boolean | null;
  openAccessPdf: {
    url?: string | null;
    status?: string | null;
    license?: string | null;
    disclaimer?: string | null;
  } | null;
  fieldsOfStudy: string[] | null;
  s2FieldsOfStudy: Array<{ category?: string; source?: string }> | null;
  publicationTypes: string[] | null;
  tldr: { text?: string; model?: string } | null;
}

export interface SemanticScholarSearchParams {
  query: string;
  year_from?: number;
  year_to?: number;
  min_citation_count?: number;
  open_access?: boolean;
  fields_of_study?: string;
  publication_types?: string;
  venue?: string;
  sort?: SemanticScholarSort;
  limit?: number;
  offset?: number;
  token?: string;
}

export interface SemanticScholarSearchResponse {
  total: number;
  offset: number;
  next: number | null;
  token: string | null;
  data: SemanticScholarPaper[];
}

export interface SemanticScholarSearchHistory {
  id: string;
  query: string;
  filters: Record<string, unknown>;
  sort: SemanticScholarSort;
  result_count: number;
  created_at: string;
}

export interface SemanticScholarFavorite {
  id: string;
  semantic_scholar_paper_id: string;
  paper: SemanticScholarPaper;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export function normalizeSemanticScholarPaper(
  value: Partial<SemanticScholarPaper> | null | undefined
): SemanticScholarPaper {
  const paper = value ?? {};
  const authors = Array.isArray(paper.authors)
    ? paper.authors
        .filter((author): author is SemanticScholarAuthor => Boolean(author))
        .map((author) => ({
          authorId: typeof author.authorId === "string" ? author.authorId : null,
          name: typeof author.name === "string" ? author.name : null,
        }))
    : [];

  return {
    paperId: typeof paper.paperId === "string" ? paper.paperId : "",
    corpusId: typeof paper.corpusId === "number" ? paper.corpusId : null,
    externalIds:
      paper.externalIds && typeof paper.externalIds === "object"
        ? paper.externalIds
        : null,
    url: typeof paper.url === "string" ? paper.url : null,
    title: typeof paper.title === "string" ? paper.title : null,
    abstract: typeof paper.abstract === "string" ? paper.abstract : null,
    year: typeof paper.year === "number" ? paper.year : null,
    publicationDate:
      typeof paper.publicationDate === "string" ? paper.publicationDate : null,
    authors,
    venue: typeof paper.venue === "string" ? paper.venue : null,
    citationCount:
      typeof paper.citationCount === "number" ? paper.citationCount : null,
    referenceCount:
      typeof paper.referenceCount === "number" ? paper.referenceCount : null,
    influentialCitationCount:
      typeof paper.influentialCitationCount === "number"
        ? paper.influentialCitationCount
        : null,
    isOpenAccess:
      typeof paper.isOpenAccess === "boolean" ? paper.isOpenAccess : null,
    openAccessPdf:
      paper.openAccessPdf && typeof paper.openAccessPdf === "object"
        ? paper.openAccessPdf
        : null,
    fieldsOfStudy: Array.isArray(paper.fieldsOfStudy)
      ? paper.fieldsOfStudy
      : null,
    s2FieldsOfStudy: Array.isArray(paper.s2FieldsOfStudy)
      ? paper.s2FieldsOfStudy
      : null,
    publicationTypes: Array.isArray(paper.publicationTypes)
      ? paper.publicationTypes
      : null,
    tldr: paper.tldr && typeof paper.tldr === "object" ? paper.tldr : null,
  };
}

export const semanticScholarApi = {
  async search(
    params: SemanticScholarSearchParams
  ): Promise<SemanticScholarSearchResponse> {
    const resp = await apiClient.get<SemanticScholarSearchResponse>("/papers/search", {
      params,
    });
    const payload = resp.data;
    return {
      total: typeof payload.total === "number" ? payload.total : 0,
      offset: typeof payload.offset === "number" ? payload.offset : 0,
      next: typeof payload.next === "number" ? payload.next : null,
      token: typeof payload.token === "string" ? payload.token : null,
      data: Array.isArray(payload.data)
        ? payload.data
            .map(normalizeSemanticScholarPaper)
            .filter((paper) => paper.paperId)
        : [],
    };
  },

  async importToWorkspace(
    workspaceId: string,
    semanticScholarPaperId: string
  ): Promise<Paper> {
    const resp = await apiClient.post<Paper>(
      `/workspaces/${workspaceId}/papers/import-from-s2`,
      { semantic_scholar_paper_id: semanticScholarPaperId }
    );
    return resp.data;
  },

  async listHistory(): Promise<SemanticScholarSearchHistory[]> {
    const resp = await apiClient.get<SemanticScholarSearchHistory[]>("/papers/search/history");
    return resp.data;
  },

  async deleteHistory(historyId: string): Promise<void> {
    await apiClient.delete(`/papers/search/history/${historyId}`);
  },

  async listFavorites(): Promise<SemanticScholarFavorite[]> {
    const resp = await apiClient.get<SemanticScholarFavorite[]>("/papers/favorites");
    return Array.isArray(resp.data)
      ? resp.data.map((favorite) => ({
          ...favorite,
          paper: normalizeSemanticScholarPaper(favorite.paper),
        }))
      : [];
  },

  async saveFavorite(paper: SemanticScholarPaper): Promise<SemanticScholarFavorite> {
    const resp = await apiClient.post<SemanticScholarFavorite>("/papers/favorites", { paper });
    return {
      ...resp.data,
      paper: normalizeSemanticScholarPaper(resp.data.paper),
    };
  },

  async deleteFavorite(paperId: string): Promise<void> {
    await apiClient.delete(`/papers/favorites/${encodeURIComponent(paperId)}`);
  },
};

export default semanticScholarApi;
