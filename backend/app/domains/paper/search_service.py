"""Database operations for paper search history and favorites."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domains.paper.search_models import PaperSearchFavorite, PaperSearchHistory


class PaperSearchService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record_history(
        self,
        *,
        query: str,
        filters: dict,
        sort: str,
        result_count: int,
    ) -> PaperSearchHistory:
        row = PaperSearchHistory(
            query=query,
            filters=filters,
            sort=sort,
            result_count=result_count,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_history(self, *, limit: int, offset: int) -> list[PaperSearchHistory]:
        query = (
            select(PaperSearchHistory)
            .order_by(PaperSearchHistory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.execute(query).scalars().all())

    def delete_history(self, history_id: str) -> bool:
        result = self.db.execute(
            delete(PaperSearchHistory).where(PaperSearchHistory.id == history_id)
        )
        self.db.commit()
        return bool(result.rowcount)

    def upsert_favorite(self, *, paper: dict, note: str | None) -> PaperSearchFavorite:
        paper_id = str(paper.get("paperId") or "").strip()
        if not paper_id:
            raise ValueError("paper.paperId is required")
        row = self.db.execute(
            select(PaperSearchFavorite).where(
                PaperSearchFavorite.semantic_scholar_paper_id == paper_id
            )
        ).scalar_one_or_none()
        if row is None:
            row = PaperSearchFavorite(
                semantic_scholar_paper_id=paper_id,
                paper=paper,
                note=note,
            )
            self.db.add(row)
        else:
            row.paper = paper
            row.note = note
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_favorites(self, *, limit: int, offset: int) -> list[PaperSearchFavorite]:
        query = (
            select(PaperSearchFavorite)
            .order_by(PaperSearchFavorite.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.execute(query).scalars().all())

    def delete_favorite(self, paper_id: str) -> bool:
        result = self.db.execute(
            delete(PaperSearchFavorite).where(
                PaperSearchFavorite.semantic_scholar_paper_id == paper_id
            )
        )
        self.db.commit()
        return bool(result.rowcount)
