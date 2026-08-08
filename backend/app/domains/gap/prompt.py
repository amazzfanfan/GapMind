"""Versioned model instruction for specialized gap extraction."""

PROMPT_VERSION = "gap-schema3-v1"

TRAINING_INSTRUCTION = """阅读给定的一篇计算机科学论文核心章节 Markdown，抽取核心科研实体、实体关系、核心技术路线和核心问题。输入已去除实验、结果、消融、实现细节、附录、参考文献和致谢；不要补充被删除章节中的信息。只输出一个可解析的 JSON 对象，不要输出思考过程、Markdown 代码围栏、解释、前言或结语。

输出必须严格遵守精简 Schema 3.0。顶层字段必须且只能是 schema_version、paper、entities、relations、methods、problems。schema_version 固定为 "3.0"。

entities.type 只能是 RESEARCH_PROBLEM、TASK、METHOD、MODEL、DOMAIN、OTHER_SCIENTIFIC_TERM，禁止 DATASET、METRIC、RESULT。entities 最多 15 条，其中 OTHER_SCIENTIFIC_TERM 最多 5 条。

relations.relation_type 只能是 ADDRESSES、USES、APPLIED_TO、EXTENDS、HAS_LIMITATION、PART_OF、RELATED_TO，最多 15 条。ADDRESSES 和 HAS_LIMITATION 必须是 METHOD → RESEARCH_PROBLEM，同一方法—问题对不得同时存在这两类关系。

methods 必须为 1 至 2 条。method_strategy_zh 是可跨论文复用的主要机制＋作用形式短标签，不得直接使用论文品牌方法名；mechanism_zh 简述机制。

problems 必须为 1 至 3 条。problem_label_zh 必须与对应 RESEARCH_PROBLEM 实体的 name_normalized_zh 完全一致，并直接表达不足、障碍、局限或未解决状态。problem_type 只能是 prior_work_gap 或 residual_limitation。prior_work_gap 必须由入选 METHOD 通过 ADDRESSES 指向；residual_limitation 必须由入选 METHOD 通过 HAS_LIMITATION 指向。

ID 格式分别为 E1、R1、M1、P1，所有引用必须指向存在且类型正确的实体。禁止输出 evidence、evidence_ids、paper_id、document_id、research_problems、source_file、year、venue、doi、arxiv_id、components、processing_notes。无法确定的内容不得编造。无论何时都必须闭合 JSON。

输出结构：
{
  "schema_version": "3.0",
  "paper": {"paper_name": "论文标题", "authors": [], "research_domain": []},
  "entities": [{"entity_id": "E1", "name_original": "原文名称", "name_normalized_zh": "中文名称", "type": "RESEARCH_PROBLEM", "description_zh": "说明"}],
  "relations": [{"relation_id": "R1", "source_entity_id": "E2", "relation_type": "ADDRESSES", "target_entity_id": "E1"}],
  "methods": [{"method_id": "M1", "corresponding_entity_id": "E2", "method_strategy_zh": "技术路线短标签", "mechanism_zh": "机制"}],
  "problems": [{"problem_id": "P1", "corresponding_entity_id": "E1", "problem_label_zh": "问题短标签", "problem_type": "prior_work_gap", "description_zh": "说明"}]
}"""


def repair_prompt(errors: list[str]) -> str:
    rendered = "\n".join(f"- {error}" for error in errors[:30])
    return f"""上一份 JSON 未通过 Schema 3.0 校验。请根据错误重新输出一份完整 JSON，不要解释，不要只输出补丁。

校验错误：
{rendered}

修复检查：
1. entities.type 只能是 RESEARCH_PROBLEM、TASK、METHOD、MODEL、DOMAIN、OTHER_SCIENTIFIC_TERM；删除 DATASET、METRIC、RESULT 以及不服务核心方法和问题的实体。
2. 每个 problem 必须引用不同且有效的 RESEARCH_PROBLEM，problem_label_zh 与实体中文名称完全一致。
3. prior_work_gap 使用 ADDRESSES，residual_limitation 使用 HAS_LIMITATION。
4. ADDRESSES/HAS_LIMITATION 只能是 METHOD → RESEARCH_PROBLEM，同一方法—问题对不能同时使用两类关系。
5. 修正引用或创建必要实体，删除悬空、重复、方向错误的关系。
6. 顶层只能有 schema_version、paper、entities、relations、methods、problems。"""

