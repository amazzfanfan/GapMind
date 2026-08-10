"""Controlled Agent API tests; no external model, Milvus, Redis, or Docker calls."""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.domains.agent.service import AgentService
from app.domains.discover.models import ResearchPlan
from app.domains.retrieval.schemas import RetrievalResponse, RetrievalResultItem


@dataclass
class FakeResponse:
    content: str
    model: str = "fake-deepseek"
    prompt_tokens: int = 20
    completion_tokens: int = 30
    total_tokens: int = 50


class FakeGateway:
    api_key = "test-key"

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def chat_completion(self, messages, **kwargs):
        return FakeResponse(json.dumps(self.payload, ensure_ascii=False))


def _workspace_conversation(client):
    workspace = client.post("/api/v1/workspaces", json={"name": "Agent WS"}).json()
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"title": "Agent 对话", "workspace_id": workspace["id"]},
    ).json()
    return workspace, conversation


def _retrieval(workspace_id: str) -> RetrievalResponse:
    return RetrievalResponse(
        workspace_id=workspace_id,
        status="succeeded",
        items=[
            RetrievalResultItem(
                paper_id="paper-1",
                paper_title="Grounded Paper",
                chunk_id="chunk-1",
                section="Methods",
                text="The method uses topology-aware\x00 contrastive learning.",
                score=0.91,
            )
        ],
    )


def test_research_agent_persists_steps_artifact_and_confirmed_plan(
    client, db_session: Session, monkeypatch
):
    workspace, conversation = _workspace_conversation(client)
    with patch("app.domains.agent.router.spawn_agent_task", return_value="celery-agent"):
        response = client.post(
            f"/api/v1/workspaces/{workspace['id']}/agent-runs",
            json={
                "agent_type": "research_plan",
                "prompt": "设计图神经网络鲁棒性实验",
                "conversation_id": conversation["id"],
                "input": {"resource_constraints": "单张 GPU"},
            },
        )
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    monkeypatch.setattr(
        "app.domains.agent.service.semantic_search", lambda **_: _retrieval(workspace["id"])
    )
    gateway = FakeGateway(
        {
            "title": "拓扑感知对比学习的分布偏移鲁棒性研究",
            "research_question": "拓扑感知对比学习能否提升分布偏移下的鲁棒性？",
            "hypothesis": "拓扑正则能够提高 OOD 准确率。",
            "scope_and_assumptions": "节点分类",
            "datasets": ["Cora"],
            "baselines": ["GCN"],
            "metrics": ["OOD accuracy"],
            "validation_steps": ["构造分布偏移", "比较基线"],
            "expected_supporting_result": "准确率提升",
            "falsification_criteria": "提升小于 1%",
            "risks": ["数据规模有限"],
            "resource_constraints": "单张 GPU",
            "evidence_refs": ["E1"],
        }
    )
    AgentService(db_session, gateway=gateway).execute(run_id)

    detail = client.get(f"/api/v1/workspaces/{workspace['id']}/agent-runs/{run_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "waiting_for_user"
    assert len(body["steps"]) == 3
    assert body["artifacts"][0]["filename"] == "research_plan.md"

    confirmed = client.post(f"/api/v1/workspaces/{workspace['id']}/agent-runs/{run_id}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    plan_id = confirmed.json()["research_plan_id"]
    plan = db_session.get(ResearchPlan, plan_id)
    assert plan is not None
    assert plan.title == "拓扑感知对比学习的分布偏移鲁棒性研究"
    assert plan.source_type == "agent"
    assert plan.opportunity_id is None


def test_deep_research_agent_binds_plan_generates_grounded_report_and_waits_for_review(
    client, db_session: Session, monkeypatch
):
    workspace, conversation = _workspace_conversation(client)
    plan = ResearchPlan(
        workspace_id=workspace["id"],
        opportunity_id=None,
        opportunity_version_id=None,
        source_type="opportunity",
        status="draft",
        title="图神经网络分布偏移鲁棒性研究",
        research_question="拓扑约束能否提升图神经网络在分布偏移下的鲁棒性？",
        hypothesis="拓扑约束能够提高 OOD 准确率。",
        scope_and_assumptions="节点分类",
        datasets=["Cora"],
        baselines=["GCN"],
        metrics=["OOD accuracy"],
        validation_steps=["构造分布偏移", "比较基线"],
        expected_supporting_result="准确率提升",
        falsification_criteria="提升小于 1%",
        risks=["数据规模有限"],
        resource_constraints="单张 GPU",
    )
    db_session.add(plan)
    db_session.commit()
    with patch("app.domains.agent.router.spawn_agent_task", return_value="celery-deep"):
        response = client.post(
            f"/api/v1/workspaces/{workspace['id']}/agent-runs",
            json={
                "agent_type": "deep_research",
                "prompt": "综合支持证据和反证，精炼实验方案",
                "conversation_id": conversation["id"],
                "input": {"research_plan_id": plan.id},
            },
        )
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    assert response.json()["context_snapshot"]["research_plan"]["title"] == plan.title

    monkeypatch.setattr(
        "app.domains.agent.service.semantic_search", lambda **_: _retrieval(workspace["id"])
    )
    gateway = FakeGateway(
        {
            "title": "拓扑约束下的图神经网络鲁棒性深度研究",
            "executive_summary": "现有证据支持继续验证，但跨数据集外推仍不确定。",
            "research_landscape": "现有工作主要关注单一分布偏移设置。",
            "supporting_findings": ["拓扑感知机制与鲁棒性提升相关 [W1]"],
            "counter_findings": ["尚缺少跨数据集独立复现"],
            "unresolved_questions": ["提升是否依赖图同配性？"],
            "refined_hypothesis": "在中高同配图上，拓扑约束可稳定提升 OOD 准确率。",
            "recommended_methodology": ["按同配性分层实验"],
            "proposed_method": {
                "name_zh": "拓扑约束鲁棒学习框架",
                "core_idea": "联合优化分类目标和拓扑一致性目标。",
                "modules": ["图编码器", "拓扑一致性正则器"],
                "objective_function": {
                    "latex": "\\mathcal{L}=\\mathcal{L}_{task}+\\lambda\\mathcal{L}_{topo}",
                    "explanation": "最小化任务损失与拓扑一致性损失的加权和。",
                    "symbols": "lambda 为拓扑正则强度。",
                },
                "formulas": [
                    {
                        "name": "联合训练目标",
                        "latex": "\\mathcal{L}=\\mathcal{L}_{task}+\\lambda\\mathcal{L}_{topo}",
                        "explanation": "在完成节点分类的同时约束拓扑表示。",
                        "symbols": "lambda 为拓扑正则强度。",
                    },
                    {
                        "name": "鲁棒性增益",
                        "latex": "\\Delta_{ood}=Acc_{ours}^{ood}-Acc_{base}^{ood}",
                        "explanation": "衡量候选方法相对基线的分布外准确率增益。",
                        "symbols": "Acc 表示分布外准确率。",
                    },
                ],
                "algorithm_steps": ["编码图结构", "计算联合损失", "反向传播"],
                "implementation_details": ["使用 PyTorch Geometric 实现"],
            },
            "experimental_design": {
                "datasets": ["Cora", "Citeseer"],
                "baselines": ["GCN", "GraphSAGE"],
                "metrics": ["OOD accuracy", "Macro-F1", "训练时间"],
                "ablations": ["移除拓扑正则"],
                "statistical_tests": ["五个随机种子的配对 t 检验"],
                "expected_supporting_results": ["OOD accuracy 稳定提升"],
                "falsification_criteria": ["提升不显著或仅在单一数据集出现"],
            },
            "experiment_plan": ["在 Cora 上构造偏移", "进行消融"],
            "novelty_assessment": "边界条件验证具有增量新颖性。",
            "risk_register": ["证据仅来自一个工作区片段"],
            "next_actions": ["补充第二个独立数据集"],
            "evidence_refs": ["W1", "NOT_REAL"],
        }
    )
    AgentService(db_session, gateway=gateway).execute(run_id)

    detail = client.get(f"/api/v1/workspaces/{workspace['id']}/agent-runs/{run_id}").json()
    assert detail["status"] == "waiting_for_user"
    assert [step["stage"] for step in detail["steps"]] == [
        "plan_binding",
        "evidence_collection",
        "deep_synthesis",
        "evidence_gate",
    ]
    assert detail["result"]["evidence_refs"] == ["W1"]
    assert len(detail["result"]["proposed_method"]["formulas"]) == 2
    assert detail["result"]["experimental_design"]["datasets"] == ["Cora", "Citeseer"]
    assert "数学定义与候选公式" in detail["artifacts"][0]["content"]
    assert detail["artifacts"][0]["filename"] == "deep_research_report.md"

    confirmed = client.post(f"/api/v1/workspaces/{workspace['id']}/agent-runs/{run_id}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["research_plan_id"] == plan.id
    assert confirmed.json()["run"]["result"]["review_status"] == "confirmed"


def test_code_agent_requires_plan_and_generates_safe_downloadable_files(
    client, db_session: Session, monkeypatch
):
    workspace, conversation = _workspace_conversation(client)
    missing = client.post(
        f"/api/v1/workspaces/{workspace['id']}/agent-runs",
        json={
            "agent_type": "code_generation",
            "prompt": "生成代码",
            "conversation_id": conversation["id"],
            "input": {},
        },
    )
    assert missing.status_code == 422

    plan = ResearchPlan(
        workspace_id=workspace["id"],
        opportunity_id=None,
        opportunity_version_id=None,
        source_type="agent",
        status="draft",
        research_question="Test graph robustness",
        hypothesis="Regularization improves OOD",
        scope_and_assumptions="Node classification",
        datasets=["Cora"],
        baselines=["GCN"],
        metrics=["accuracy"],
        validation_steps=["train", "evaluate"],
        expected_supporting_result="gain",
        falsification_criteria="no gain",
        risks=[],
        resource_constraints="CPU",
    )
    db_session.add(plan)
    db_session.commit()
    with patch("app.domains.agent.router.spawn_agent_task", return_value="celery-code"):
        created = client.post(
            f"/api/v1/workspaces/{workspace['id']}/agent-runs",
            json={
                "agent_type": "code_generation",
                "prompt": "生成最小实验",
                "conversation_id": conversation["id"],
                "input": {"research_plan_id": plan.id, "framework": "PyTorch"},
            },
        )
    assert created.status_code == 202, created.text
    run_id = created.json()["id"]
    monkeypatch.setattr(
        "app.domains.agent.service.semantic_search", lambda **_: _retrieval(workspace["id"])
    )
    gateway = FakeGateway(
        {
            "summary": "minimal project",
            "files": [
                {"path": "README.md", "language": "markdown", "content": "# Experiment"},
                {"path": "src/train.py", "language": "python", "content": "print('train')"},
                {"path": "../escape.py", "language": "python", "content": "bad"},
            ],
        }
    )
    AgentService(db_session, gateway=gateway).execute(run_id)
    detail = client.get(f"/api/v1/workspaces/{workspace['id']}/agent-runs/{run_id}").json()
    assert detail["status"] == "succeeded"
    assert {item["filename"] for item in detail["artifacts"]} == {"README.md", "src/train.py"}
    bundle = client.get(f"/api/v1/workspaces/{workspace['id']}/agent-runs/{run_id}/bundle")
    assert bundle.status_code == 200
    assert bundle.headers["content-type"] == "application/zip"


def test_agent_workspace_isolation_and_validation_is_disabled_by_default(
    client, db_session: Session
):
    workspace, conversation = _workspace_conversation(client)
    other = client.post("/api/v1/workspaces", json={"name": "Other"}).json()
    plan = ResearchPlan(
        workspace_id=workspace["id"],
        opportunity_id=None,
        opportunity_version_id=None,
        source_type="agent",
        status="draft",
        research_question="Q",
        hypothesis="H",
        scope_and_assumptions="",
        datasets=[],
        baselines=[],
        metrics=[],
        validation_steps=[],
        expected_supporting_result="",
        falsification_criteria="",
        risks=[],
        resource_constraints="",
    )
    db_session.add(plan)
    db_session.commit()
    with patch("app.domains.agent.router.spawn_agent_task", return_value="celery-code"):
        created = client.post(
            f"/api/v1/workspaces/{workspace['id']}/agent-runs",
            json={
                "agent_type": "code_generation",
                "prompt": "code",
                "conversation_id": conversation["id"],
                "input": {"research_plan_id": plan.id},
            },
        ).json()
    assert (
        client.get(f"/api/v1/workspaces/{other['id']}/agent-runs/{created['id']}").status_code
        == 404
    )
    run = AgentService(db_session).get(workspace["id"], created["id"])
    run.status = "succeeded"
    db_session.commit()
    disabled = client.post(f"/api/v1/workspaces/{workspace['id']}/agent-runs/{run.id}/validate")
    assert disabled.status_code == 422
    assert disabled.json()["detail"]["error"] == "agent_execution_disabled"
