"""Scan a paper's parsed_markdown for passages relevant to a claim.

This is a manual-review helper for the RG-8 counter-evidence gold
confirmation (docs/rg8_counter_evidence_gold_review.md). It finds the
passages of a target paper most likely to support/qualify/contradict a
given claim, so a human can quickly judge whether the gold annotation is
correct — WITHOUT having to read the whole paper.

Method: naive keyword overlap. The claim is split into keywords (stopwords
removed, case-folded), then each markdown paragraph is scored by how many
distinct keywords it contains. The top passages are printed with section
context and char offsets so the reviewer can jump to the原文.

This is intentionally simple — it's a *locator*, not a judge. The human
still decides whether the passage actually qualifies/contradicts the claim.

Usage (from backend/):

    .venv/Scripts/python.exe scripts/evidence_scan.py \
        --workspace-id 123100ea-e75b-4110-9048-1f5b92668c32 \
        --claim "Adding more explanation constraints always improves prediction accuracy." \
        --paper-ref "VGIB"
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

REPO_ROOT = BACKEND_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import app.db.models  # noqa: E402,F401
from app.db.session import SessionLocal  # noqa: E402
from app.domains.artifact.models import Artifact  # noqa: E402
from app.domains.artifact.service import ArtifactService  # noqa: E402
from evaluation.retrieval.run_eval import resolve_paper_ref  # noqa: E402

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "of", "for", "with", "on", "in",
    "at", "by", "to", "is", "are", "was", "were", "be", "been", "being",
    "it", "its", "this", "that", "these", "those", "always", "never",
    "more", "most", "all", "any", "our", "we", "their", "them", "they",
    "than", "from", "as", "into", "such", "can", "may", "might", "would",
    "could", "should", "will", "does", "do", "not", "no", "improves",
    "prediction", "accuracy", "explanation", "explanations",
})


def _keywords(claim: str) -> list[str]:
    return [
        w for w in re.findall(r"[a-zA-Z][a-zA-Z-]{2,}", claim.casefold())
        if w not in _STOPWORDS
    ]


def _split_paragraphs(md: str) -> list[tuple[int, str]]:
    """Split markdown into (char_offset, text) paragraphs."""
    out: list[tuple[int, str]] = []
    for m in re.finditer(r"(?m)^[^\n]+(?:\n(?![#\n])[^\n]+)*", md):
        text = m.group(0).strip()
        if len(text) < 20:  # skip headings / noise
            continue
        out.append((m.start(), text))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--claim", required=True)
    parser.add_argument("--paper-ref", required=True)
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        paper = resolve_paper_ref(db, args.workspace_id, args.paper_ref)
        if paper is None:
            print(f"paper not resolved in workspace: {args.paper_ref}")
            print("(title may be abbreviated — check exact title first)")
            return 1
        if not paper.parsed_markdown_artifact_id:
            print(f"paper has no parsed_markdown: {paper.title}")
            return 1

        md_artifact = db.get(Artifact, paper.parsed_markdown_artifact_id)
        md_path = ArtifactService(db).resolve_abs_path(md_artifact)
        md = md_path.read_text(encoding="utf-8")

        keywords = _keywords(args.claim)
        print(f"paper : {paper.title}")
        print(f"claim : {args.claim}")
        print(f"keywords: {keywords}")
        print(f"markdown: {md_path} ({len(md)} chars)")
        print()

        paragraphs = _split_paragraphs(md)
        scored = []
        for offset, text in paragraphs:
            text_l = text.casefold()
            hits = [k for k in keywords if k in text_l]
            if hits:
                scored.append((len(hits), offset, text, hits))

        scored.sort(key=lambda x: x[0], reverse=True)
        print(f"== Top {args.top} most relevant passages ==")
        for rank, (n_hits, offset, text, hits) in enumerate(scored[: args.top], 1):
            # find section heading before this offset
            heading = ""
            for hm in re.finditer(r"(?m)^##+\s+(.*)", md):
                if hm.start() < offset:
                    heading = hm.group(1).strip()
                else:
                    break
            print(f"\n--- #{rank} (hits={n_hits}: {', '.join(hits)}) offset={offset} section=[{heading}] ---")
            print(text[:1200])
            print("...")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())