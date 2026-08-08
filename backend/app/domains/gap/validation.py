"""Parsing and semantic validation for Schema 3.0 model output."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from app.domains.gap.schemas import GapAnnotationOutput

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_model_json(content: str) -> dict[str, Any]:
    cleaned = THINK_BLOCK.sub("", content).strip()
    cleaned = CODE_FENCE.sub("", cleaned).strip()
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("model response does not contain a JSON object")


def _schema_errors(error: ValidationError) -> list[str]:
    rendered: list[str] = []
    for item in error.errors(include_url=False):
        location = ".".join(str(part) for part in item["loc"])
        bad_input = item.get("input")
        suffix = f" (received {bad_input!r})" if bad_input is not None else ""
        rendered.append(f"JSON Schema {location}: {item['msg']}{suffix}")
    return rendered


def validate_annotation(value: dict[str, Any]) -> tuple[GapAnnotationOutput | None, list[str]]:
    try:
        output = GapAnnotationOutput.model_validate(value)
    except ValidationError as exc:
        return None, _schema_errors(exc)

    errors: list[str] = []
    entities = {item.entity_id: item for item in output.entities}

    for collection_name, ids in (
        ("entities", [item.entity_id for item in output.entities]),
        ("relations", [item.relation_id for item in output.relations]),
        ("methods", [item.method_id for item in output.methods]),
        ("problems", [item.problem_id for item in output.problems]),
    ):
        if len(ids) != len(set(ids)):
            errors.append(f"{collection_name} 包含重复 ID。")

    for relation in output.relations:
        source = entities.get(relation.source_entity_id)
        target = entities.get(relation.target_entity_id)
        if source is None or target is None:
            errors.append(f"{relation.relation_id} 引用了不存在的实体。")
            continue
        if relation.relation_type in {"ADDRESSES", "HAS_LIMITATION"} and (
            source.type != "METHOD" or target.type != "RESEARCH_PROBLEM"
        ):
            errors.append(
                f"{relation.relation_id} 的 {relation.relation_type} 必须是 METHOD → RESEARCH_PROBLEM。"
            )

    board_pairs: dict[tuple[str, str], set[str]] = {}
    for relation in output.relations:
        if relation.relation_type in {"ADDRESSES", "HAS_LIMITATION"}:
            key = (relation.source_entity_id, relation.target_entity_id)
            board_pairs.setdefault(key, set()).add(relation.relation_type)
    for (source, target), kinds in board_pairs.items():
        if kinds == {"ADDRESSES", "HAS_LIMITATION"}:
            errors.append(f"同一方法—问题对 {source} → {target} 同时使用了两类棋盘关系。")

    selected_methods: set[str] = set()
    for method in output.methods:
        entity = entities.get(method.corresponding_entity_id)
        if entity is None or entity.type != "METHOD":
            errors.append(f"{method.method_id} 未引用有效 METHOD 实体。")
        else:
            selected_methods.add(entity.entity_id)
    if len(selected_methods) != len(output.methods):
        errors.append("多个 methods 可能引用了同一个或无效的 METHOD 实体。")

    selected_problems: set[str] = set()
    for problem in output.problems:
        entity = entities.get(problem.corresponding_entity_id)
        if entity is None or entity.type != "RESEARCH_PROBLEM":
            errors.append(f"{problem.problem_id} 未引用有效 RESEARCH_PROBLEM 实体。")
            continue
        selected_problems.add(entity.entity_id)
        if problem.problem_label_zh != entity.name_normalized_zh:
            errors.append(f"{problem.problem_id}.problem_label_zh 与对应实体名称不一致。")
        required = "ADDRESSES" if problem.problem_type == "prior_work_gap" else "HAS_LIMITATION"
        if not any(
            relation.source_entity_id in selected_methods
            and relation.target_entity_id == entity.entity_id
            and relation.relation_type == required
            for relation in output.relations
        ):
            errors.append(f"{problem.problem_id} 缺少入选方法指向它的 {required} 关系。")
    if len(selected_problems) != len(output.problems):
        errors.append("多个 problems 可能引用了同一个或无效的 RESEARCH_PROBLEM 实体。")

    return (output if not errors else None), errors
