from __future__ import annotations

import json
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domains.artifact.models import Artifact
from app.domains.gap.markdown import compact_markdown
from app.domains.gap.models import PaperGapAnnotation
from app.domains.gap.service import GapService
from app.domains.gap.validation import validate_annotation
from app.domains.paper.models import Paper
from app.domains.workspace.models import Workspace
from app.gateway.gap_extractor import OllamaGapExtractor


def _output(
    *,
    problem_entity: str = "E2",
    problem_label: str = "解释稳定性不足",
    problem_type: str = "prior_work_gap",
    relation_type: str = "ADDRESSES",
) -> dict:
    return {
        "schema_version": "3.0",
        "paper": {
            "paper_name": "Paper",
            "authors": ["Author"],
            "research_domain": ["Graph Neural Networks"],
        },
        "entities": [
            {
                "entity_id": "E1",
                "name_original": "method",
                "name_normalized_zh": "方法",
                "type": "METHOD",
                "description_zh": "method",
            },
            {
                "entity_id": problem_entity,
                "name_original": "problem",
                "name_normalized_zh": problem_label,
                "type": "RESEARCH_PROBLEM",
                "description_zh": "problem",
            },
        ],
        "relations": [
            {
                "relation_id": "R1",
                "source_entity_id": "E1",
                "relation_type": relation_type,
                "target_entity_id": problem_entity,
            }
        ],
        "methods": [
            {
                "method_id": "M1",
                "corresponding_entity_id": "E1",
                "method_strategy_zh": "子图扰动式解释",
                "mechanism_zh": "通过扰动定位关键子图",
            }
        ],
        "problems": [
            {
                "problem_id": "P1",
                "corresponding_entity_id": problem_entity,
                "problem_label_zh": problem_label,
                "problem_type": problem_type,
                "description_zh": "问题说明",
            }
        ],
    }


def test_schema3_business_validation() -> None:
    parsed, errors = validate_annotation(_output())
    assert parsed is not None
    assert errors == []

    invalid = _output()
    invalid["entities"][1]["type"] = "DATASET"
    parsed, errors = validate_annotation(invalid)
    assert parsed is None
    assert any("DATASET" in error for error in errors)


def test_compact_markdown_drops_experiments_but_keeps_conclusion() -> None:
    source = """# Introduction
Core motivation.
# Experiments
Dataset and scores.
# Conclusion
The remaining limitation matters.
# Appendix
Extra tables.
"""

    compacted = compact_markdown(source)

    assert "Core motivation" in compacted
    assert "Dataset and scores" not in compacted
    assert "remaining limitation" in compacted
    assert "Extra tables" not in compacted


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _Client:
    def __init__(self, contents: list[str]) -> None:
        self.contents = list(contents)
        self.calls: list[dict] = []

    def post(self, url: str, *, json: dict) -> _Response:
        self.calls.append({"url": url, "json": json})
        return _Response({"message": {"content": self.contents.pop(0)}})


def test_ollama_extractor_repairs_invalid_enum() -> None:
    invalid = _output()
    invalid["entities"][1]["type"] = "DATASET"
    client = _Client([json.dumps(invalid), json.dumps(_output())])
    extractor = OllamaGapExtractor(
        base_url="http://ollama.test:11434", model="test-model", client=client
    )

    result = extractor.extract("# Introduction\nPaper", repair_attempts=1)

    assert result.output is not None
    assert result.attempts == 2
    assert len(client.calls) == 2
    assert "DATASET" in client.calls[1]["json"]["messages"][-1]["content"]


def _annotation(
    db: Session,
    workspace: Workspace,
    artifact: Artifact,
    paper: Paper,
    output: dict,
) -> PaperGapAnnotation:
    row = PaperGapAnnotation(
        id=str(uuid4()),
        workspace_id=workspace.id,
        paper_id=paper.id,
        artifact_id=artifact.id,
        task_id=None,
        input_sha256=uuid4().hex + uuid4().hex,
        schema_version="3.0",
        prompt_version="test",
        model_provider="ollama",
        model_name="test-model",
        model_digest=None,
        model_parameters={},
        status="valid",
        attempts=1,
        raw_responses=[],
        output=output,
        validation_errors=[],
        is_deleted=False,
    )
    db.add(row)
    db.commit()
    return row


def test_deterministic_board_marks_coverage_and_explicit_limitation(
    db_session: Session, client: TestClient
) -> None:
    workspace = Workspace(
        id=str(uuid4()),
        name="Gap WS",
        keywords=[],
        active_questions=[],
        is_archived=False,
        is_deleted=False,
    )
    db_session.add(workspace)
    db_session.flush()
    artifacts: list[Artifact] = []
    papers: list[Paper] = []
    for index in range(2):
        artifact = Artifact(
            id=str(uuid4()),
            workspace_id=workspace.id,
            kind="parsed_markdown",
            file_path=f"paper-{index}.md",
            size_bytes=10,
            is_deleted=False,
        )
        paper = Paper(
            id=str(uuid4()),
            workspace_id=workspace.id,
            title=f"Paper {index}",
            authors=[],
            source="manual",
            parse_status="parsed",
            chunk_count=0,
            extract_status="not_applicable",
            is_deleted=False,
        )
        db_session.add_all([artifact, paper])
        db_session.flush()
        papers.append(paper)
        artifacts.append(artifact)

    first = _annotation(db_session, workspace, artifacts[0], papers[0], _output())
    second_output = _output(
        problem_label="跨数据集泛化不足",
        problem_type="residual_limitation",
        relation_type="HAS_LIMITATION",
    )
    second = _annotation(db_session, workspace, artifacts[1], papers[1], second_output)

    service = GapService(db_session)
    service.assign_annotation(first)
    service.assign_annotation(second)
    board = service.rebuild_board(workspace.id)

    assert len(board.method_axes) == 1
    assert len(board.problem_axes) == 2
    assert len(board.cells) == 2
    covered = next(item for item in board.cells if item["addressed"])
    candidate = next(item for item in board.cells if not item["addressed"])
    assert covered["addressed_paper_ids"] == [papers[0].id]
    assert candidate["explicit_limitation"] is True
    assert candidate["limitation_paper_ids"] == [papers[1].id]
    assert board.candidate_count == 1

    response = client.get(f"/api/v1/workspaces/{workspace.id}/gap/board")
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 1
