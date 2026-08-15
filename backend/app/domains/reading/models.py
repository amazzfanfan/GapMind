"""Reading-library and paper annotation models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin


class ReadingItem(Base, UUIDPKMixin, TimestampMixin):
    """A paper explicitly added to the user's reading library."""

    __tablename__ = "reading_items"

    paper_id: Mapped[str] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default="unread", nullable=False, index=True
    )
    last_read_page: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )


class PaperAnnotation(Base, UUIDPKMixin, TimestampMixin):
    """A durable, page-level note attached to a concrete PDF artifact."""

    __tablename__ = "paper_annotations"

    paper_id: Mapped[str] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(
        String(32), default="note", nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    selected_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    note_content: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="#fff1a8", nullable=False)
    # Reserved for the next PDF.js overlay iteration. The MVP stores an empty
    # list while still keeping the annotation API forward-compatible.
    rects: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    source_text_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
