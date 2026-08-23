"""Chat API tests use a fake gateway and never call DeepSeek."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domains.retrieval.schemas import RetrievalResponse, RetrievalResultItem


@dataclass
class FakeResponse:
    content: str
    model: str = "fake-deepseek"
    prompt_tokens: int = 10
    completion_tokens: int = 5
    total_tokens: int = 15


class FakeGateway:
    api_key = "test-key"

    def __init__(self, content: str = "这是 AI 的回答") -> None:
        self.content = content
        self.calls: list[list[dict[str, str]]] = []
        self.fail = False

    def chat_completion(self, messages, **kwargs):
        self.calls.append(messages)
        if self.fail:
            raise RuntimeError("upstream unavailable")
        return FakeResponse(self.content)

    def stream_chat_completion(self, messages, **kwargs):
        for delta in getattr(self, "stream_deltas", ["流式"]):
            yield delta


@pytest.fixture
def fake_gateway(monkeypatch):
    gateway = FakeGateway()
    monkeypatch.setattr("app.domains.chat.service.get_llm_gateway", lambda: gateway)
    return gateway


def _confirmed_plan(db_session, workspace_id: str, title: str):
    from app.domains.discover.models import ResearchOpportunity, ResearchPlan

    opportunity = ResearchOpportunity(
        workspace_id=workspace_id,
        title=title,
        summary="已确认研究机会",
        rationale="测试用机会",
        status="confirmed",
    )
    db_session.add(opportunity)
    db_session.flush()
    plan = ResearchPlan(
        workspace_id=workspace_id,
        opportunity_id=opportunity.id,
        status="draft",
        title=title,
        research_question="该方法相对 ProtGNN 是否提升鲁棒性？",
        hypothesis="拓扑约束可以提升 OOD 性能。",
        scope_and_assumptions="节点分类",
        datasets=["Cora"],
        baselines=["ProtGNN"],
        metrics=["accuracy"],
        validation_steps=["比较基线"],
        expected_supporting_result="OOD accuracy 提升",
        falsification_criteria="没有稳定提升",
        risks=[],
        resource_constraints="单张 GPU",
    )
    db_session.add(plan)
    db_session.commit()
    return plan


def test_first_send_creates_conversation_and_two_messages(client, fake_gateway):
    response = client.post(
        "/api/v1/chat/conversations/send", json={"content": "  什么是时间图神经网络？  "}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation"]["title"] == "什么是时间图神经网络？"
    assert body["user_message"]["role"] == "user"
    assert body["assistant_message"]["status"] == "completed"
    assert body["assistant_message"]["model"] == "fake-deepseek"
    assert body["assistant_message"]["total_tokens"] == 15
    assert len(fake_gateway.calls) == 1

    detail = client.get(f"/api/v1/chat/conversations/{body['conversation']['id']}").json()
    assert [item["role"] for item in detail["messages"]] == ["user", "assistant"]


def test_existing_send_includes_completed_history(client, fake_gateway):
    first = client.post("/api/v1/chat/conversations/send", json={"content": "先解释 GNN"}).json()
    client.post(
        f"/api/v1/chat/conversations/{first['conversation']['id']}/messages",
        json={"content": "再解释消息传递"},
    )

    second_context = fake_gateway.calls[-1]
    assert second_context == [
        {"role": "user", "content": "先解释 GNN"},
        {"role": "assistant", "content": "这是 AI 的回答"},
        {"role": "user", "content": "再解释消息传递"},
    ]


def test_conversation_search_rename_and_soft_delete(client, fake_gateway):
    first = client.post("/api/v1/chat/conversations/send", json={"content": "研究时间图"}).json()
    second = client.post("/api/v1/chat/conversations/send", json={"content": "研究知识图谱"}).json()

    search = client.get("/api/v1/chat/conversations", params={"query": "时间"})
    assert search.status_code == 200
    assert search.json()["total"] == 1
    assert search.json()["items"][0]["id"] == first["conversation"]["id"]

    renamed = client.patch(
        f"/api/v1/chat/conversations/{second['conversation']['id']}",
        json={"title": "新的知识图谱对话"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "新的知识图谱对话"

    assert (
        client.delete(f"/api/v1/chat/conversations/{first['conversation']['id']}").json()["deleted"]
        is True
    )
    assert (
        client.get(f"/api/v1/chat/conversations/{first['conversation']['id']}").status_code == 404
    )
    assert (
        client.post(
            f"/api/v1/chat/conversations/{first['conversation']['id']}/messages",
            json={"content": "不能继续"},
        ).status_code
        == 404
    )


def test_failed_answer_is_persisted_and_can_be_retried(client, fake_gateway):
    fake_gateway.fail = True
    response = client.post("/api/v1/chat/conversations/send", json={"content": "测试失败恢复"})
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["conversation_id"]
    assert detail["assistant_message_id"]

    conversation_id = detail["conversation_id"]
    assistant_id = detail["assistant_message_id"]
    messages = client.get(f"/api/v1/chat/conversations/{conversation_id}").json()["messages"]
    assert messages[-1]["status"] == "failed"
    assert messages[-1]["content"] == ""

    fake_gateway.fail = False
    retry = client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages/{assistant_id}/retry"
    )
    assert retry.status_code == 200
    assert retry.json()["assistant_message"]["status"] == "completed"
    assert len(fake_gateway.calls) == 2

    assert (
        client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages/{assistant_id}/retry"
        ).status_code
        == 409
    )


def test_missing_api_key_is_mapped_to_503_and_persisted(client, fake_gateway):
    fake_gateway.api_key = ""
    response = client.post("/api/v1/chat/conversations/send", json={"content": "测试未配置密钥"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == "deepseek_unavailable"
    messages = client.get(f"/api/v1/chat/conversations/{detail['conversation_id']}").json()[
        "messages"
    ]
    assert messages[-1]["status"] == "failed"


def test_validation_and_generating_conflict(client, db_session, fake_gateway):
    assert (
        client.post("/api/v1/chat/conversations/send", json={"content": "   "}).status_code == 422
    )
    assert (
        client.post("/api/v1/chat/conversations/send", json={"content": "x" * 12001}).status_code
        == 400
    )

    created = client.post("/api/v1/chat/conversations", json={}).json()
    # Insert a real generating message through the public model fixture path.
    from app.db.models import ChatMessage

    db_session.add(
        ChatMessage(
            conversation_id=created["id"],
            role="assistant",
            content="",
            status="generating",
            sequence=1,
        )
    )
    db_session.commit()

    response = client.post(
        f"/api/v1/chat/conversations/{created['id']}/messages",
        json={"content": "重复发送"},
    )
    assert response.status_code == 409


def test_workspace_chat_retrieves_persists_citations_and_opens_source(
    client,
    db_session,
    fake_gateway,
    monkeypatch,
):
    workspace = client.post(
        "/api/v1/workspaces",
        json={"name": "图学习", "topic": "图神经网络解释"},
    ).json()
    paper = client.post(
        f"/api/v1/workspaces/{workspace['id']}/papers",
        json={"title": "Interpretable Graph Models", "authors": [], "year": 2024},
    ).json()

    from app.domains.artifact.service import ArtifactService

    source_text = "Intro Evidence about graph explanations and robust evaluation."
    artifact = ArtifactService(db_session).save_upload(
        workspace_id=workspace["id"],
        filename="paper.txt",
        content=source_text.encode("utf-8"),
        mime_type="text/plain",
        kind="parsed_text",
    )

    def fake_search(**kwargs):
        assert kwargs["workspace_id"] == workspace["id"]
        assert kwargs["use_reranker"] is True
        return RetrievalResponse(
            workspace_id=workspace["id"],
            query=kwargs["query"],
            items=[
                RetrievalResultItem(
                    paper_id=paper["id"],
                    artifact_id=artifact.id,
                    chunk_id="chunk-1",
                    section="Methods",
                    text="Evidence about graph\x00 explanations and robust evaluation.",
                    score=0.91,
                    retrieval_stage="reranked",
                )
            ],
            total=1,
        )

    monkeypatch.setattr("app.domains.chat.service.semantic_search", fake_search)
    monkeypatch.setattr(
        "app.domains.chat.service.find_chunk_record",
        lambda *_: SimpleNamespace(
            source_artifact_id=artifact.id,
            start_char=6,
            end_char=source_text.index(".") + 1,
        ),
    )
    fake_gateway.content = "该论文强调了稳健评估。[E1]"

    response = client.post(
        "/api/v1/chat/conversations/send",
        json={"content": "这个工作区如何评估解释方法？", "workspace_id": workspace["id"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation"]["workspace_id"] == workspace["id"]
    assistant = body["assistant_message"]
    assert assistant["grounding_status"] == "grounded"
    assert len(assistant["citations"]) == 1
    citation = assistant["citations"][0]
    assert citation["paper_title"] == "Interpretable Graph Models"
    assert "\x00" not in citation["excerpt"]
    assert citation["start_char"] == 6
    assert "[E1]" in fake_gateway.calls[-1][0]["content"]
    assert "\x00" not in fake_gateway.calls[-1][0]["content"]

    context = client.get(
        f"/api/v1/chat/conversations/{body['conversation']['id']}"
        f"/messages/{assistant['id']}/evidence/{citation['id']}/context"
    )
    assert context.status_code == 200
    assert context.json()["available"] is True
    assert context.json()["content"] == source_text


def test_workspace_chat_without_hits_does_not_ask_llm(client, fake_gateway, monkeypatch):
    workspace = client.post("/api/v1/workspaces", json={"name": "空工作区"}).json()
    monkeypatch.setattr(
        "app.domains.chat.service.semantic_search",
        lambda **kwargs: RetrievalResponse(
            workspace_id=kwargs["workspace_id"],
            query=kwargs["query"],
            items=[],
            total=0,
        ),
    )

    response = client.post(
        "/api/v1/chat/conversations/send",
        json={"content": "总结工作区论文", "workspace_id": workspace["id"]},
    )

    assert response.status_code == 200
    assistant = response.json()["assistant_message"]
    assert assistant["grounding_status"] == "no_evidence"
    assert assistant["citations"] == []
    assert "没有检索到" in assistant["content"]
    assert fake_gateway.calls == []


def test_workspace_chat_binds_plan_and_persists_separate_sources(
    client, db_session, fake_gateway, monkeypatch
):
    workspace = client.post("/api/v1/workspaces", json={"name": "计划问答"}).json()
    plan = _confirmed_plan(db_session, workspace["id"], "拓扑约束研究计划")
    paper = client.post(
        f"/api/v1/workspaces/{workspace['id']}/papers",
        json={"title": "ProtGNN", "authors": [], "year": 2024},
    ).json()
    monkeypatch.setattr(
        "app.domains.chat.service.semantic_search",
        lambda **kwargs: RetrievalResponse(
            workspace_id=kwargs["workspace_id"],
            query=kwargs["query"],
            items=[
                RetrievalResultItem(
                    paper_id=paper["id"],
                    chunk_id="chunk-plan",
                    section="Method",
                    text="ProtGNN uses a contrastive objective.",
                    score=0.9,
                    retrieval_stage="reranked",
                )
            ],
            total=1,
        ),
    )
    fake_gateway.content = "计划提出的贡献见 [P1]；ProtGNN 论文证据见 [E1]。"

    response = client.post(
        "/api/v1/chat/conversations/send",
        json={
            "content": "此研究计划相对 ProtGNN 的贡献是什么、损失函数是什么？",
            "workspace_id": workspace["id"],
            "research_plan_id": plan.id,
        },
    )

    assert response.status_code == 200, response.text
    assistant = response.json()["assistant_message"]
    assert assistant["grounding_status"] == "grounded"
    assert [source["source_type"] for source in assistant["sources"]] == ["plan", "paper"]
    assert assistant["sources"][0]["marker"] == "P1"
    assert assistant["sources"][0]["label"] == "已确认研究计划"
    assert assistant["source_check"]["ok"] is True
    prompt = fake_gateway.calls[-1][0]["content"]
    assert "独立损失函数：研究计划未提供此字段" in prompt
    assert "只有工作区论文可以使用 [E1]" in prompt


def test_ambiguous_plan_reference_requires_selection_without_llm(
    client, db_session, fake_gateway
):
    workspace = client.post("/api/v1/workspaces", json={"name": "多计划问答"}).json()
    _confirmed_plan(db_session, workspace["id"], "计划 A")
    _confirmed_plan(db_session, workspace["id"], "计划 B")

    response = client.post(
        "/api/v1/chat/conversations/send",
        json={
            "content": "此研究计划的损失函数是什么？",
            "workspace_id": workspace["id"],
        },
    )

    assert response.status_code == 400
    assert "多个已确认研究计划" in response.json()["detail"]["message"]
    assert "计划 A" in response.json()["detail"]["message"]
    assert "计划 B" in response.json()["detail"]["message"]
    assert fake_gateway.calls == []


def test_cross_workspace_plan_is_rejected(client, db_session, fake_gateway):
    first = client.post("/api/v1/workspaces", json={"name": "当前课题"}).json()
    second = client.post("/api/v1/workspaces", json={"name": "另一个课题"}).json()
    foreign_plan = _confirmed_plan(db_session, second["id"], "跨工作区计划")

    response = client.post(
        "/api/v1/chat/conversations/send",
        json={
            "content": "请解释这个计划",
            "workspace_id": first["id"],
            "research_plan_id": foreign_plan.id,
        },
    )

    assert response.status_code == 400
    assert "属于当前工作区" in response.json()["detail"]["message"]
    assert fake_gateway.calls == []


def test_context_options_and_optional_report_code_sources_are_scoped(
    client, db_session, fake_gateway, monkeypatch
):
    from app.domains.agent.models import AgentArtifact, AgentRun

    workspace = client.post("/api/v1/workspaces", json={"name": "补充来源"}).json()
    plan = _confirmed_plan(db_session, workspace["id"], "来源边界计划")
    report_run = AgentRun(
        workspace_id=workspace["id"],
        agent_type="deep_research",
        status="succeeded",
        result={"research_plan_id": plan.id},
        input_payload={"research_plan_id": plan.id},
    )
    code_run = AgentRun(
        workspace_id=workspace["id"],
        agent_type="code_generation",
        status="succeeded",
        result={"research_plan_id": plan.id},
        input_payload={"research_plan_id": plan.id},
    )
    db_session.add_all([report_run, code_run])
    db_session.flush()
    report = AgentArtifact(
        run_id=report_run.id,
        artifact_type="deep_research_report",
        filename="report.md",
        mime_type="text/markdown",
        content="报告内说明 [E1] 只是报告自己的引用。",
        validation_status="confirmed",
    )
    code = AgentArtifact(
        run_id=code_run.id,
        artifact_type="code",
        filename="train.py",
        mime_type="text/x-python",
        content="print('candidate')",
        validation_status="not_run",
    )
    db_session.add_all([report, code])
    db_session.commit()

    options = client.get("/api/v1/chat/context-options", params={"workspace_id": workspace["id"]})
    assert options.status_code == 200, options.text
    option_body = options.json()
    assert {item["id"] for item in option_body["artifacts"]} == {report.id, code.id}
    assert {item["source_type"] for item in option_body["artifacts"]} == {"report", "code_draft"}

    paper = client.post(
        f"/api/v1/workspaces/{workspace['id']}/papers",
        json={"title": "论文证据", "authors": [], "year": 2024},
    ).json()
    monkeypatch.setattr(
        "app.domains.chat.service.semantic_search",
        lambda **kwargs: RetrievalResponse(
            workspace_id=kwargs["workspace_id"],
            query=kwargs["query"],
            items=[RetrievalResultItem(paper_id=paper["id"], text="论文事实", score=0.8)],
            total=1,
        ),
    )
    fake_gateway.content = "计划 [P1]、论文 [E1]、报告 [D1]、代码 [C1]。"
    response = client.post(
        "/api/v1/chat/conversations/send",
        json={
            "content": "结合计划和补充材料说明贡献",
            "workspace_id": workspace["id"],
            "research_plan_id": plan.id,
            "source_artifact_ids": [report.id, code.id],
        },
    )
    assert response.status_code == 200, response.text
    assistant = response.json()["assistant_message"]
    assert [item["source_type"] for item in assistant["sources"]] == [
        "plan",
        "paper",
        "report",
        "code_draft",
    ]
    assert assistant["source_check"]["ok"] is True
    prompt = fake_gateway.calls[-1][0]["content"]
    assert "报告内说明 [来源内部标记]" in prompt
    assert "代码草案，未运行验证" in prompt


def test_conversation_workspace_is_immutable(client):
    first = client.post("/api/v1/workspaces", json={"name": "课题 A"}).json()
    second = client.post("/api/v1/workspaces", json={"name": "课题 B"}).json()
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"workspace_id": first["id"]},
    ).json()

    response = client.post(
        f"/api/v1/chat/conversations/{conversation['id']}/messages",
        json={"content": "切换课题", "workspace_id": second["id"]},
    )
    assert response.status_code == 409

    missing = client.post(
        "/api/v1/chat/conversations",
        json={"workspace_id": str(uuid4())},
    )
    assert missing.status_code == 404


def test_stream_message_emits_sse_events(client, fake_gateway):
    fake_gateway.stream_deltas = ["第一", "段", "内容"]
    conversation = client.post("/api/v1/chat/conversations", json={"title": "stream"}).json()
    resp = client.post(
        f"/api/v1/chat/conversations/{conversation['id']}/messages/stream",
        json={"content": "hi"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.text
    assert '"type": "start"' in body
    assert '"type": "token"' in body
    assert '"content": "第一"' in body
    assert '"content": "内容"' in body
    assert '"type": "done"' in body
    # persisted assistant message is complete
    detail = client.get(f"/api/v1/chat/conversations/{conversation['id']}").json()
    assistant = [m for m in detail["messages"] if m["role"] == "assistant"][-1]
    assert assistant["content"] == "第一段内容"
    assert assistant["status"] == "completed"


def test_stream_retrieval_failure_emits_sse_error_and_marks_failed(
    client,
    monkeypatch,
):
    workspace = client.post(
        "/api/v1/workspaces",
        json={"name": "向量服务异常工作区"},
    ).json()
    conversation = client.post(
        "/api/v1/chat/conversations",
        json={"title": "retrieval failure", "workspace_id": workspace["id"]},
    ).json()
    monkeypatch.setattr(
        "app.domains.chat.service.semantic_search",
        lambda **kwargs: RetrievalResponse(
            workspace_id=kwargs["workspace_id"],
            query=kwargs["query"],
            status="failed",
            error="embedding provider unavailable",
            diagnostic_code="embedding_unavailable",
        ),
    )

    resp = client.post(
        f"/api/v1/chat/conversations/{conversation['id']}/messages/stream",
        json={"content": "检索失败时应可恢复"},
    )

    assert resp.status_code == 200, resp.text
    assert '"type": "error"' in resp.text
    assert "无法生成查询向量" in resp.text
    assert '"diagnostic_code": "embedding_unavailable"' in resp.text
    detail = client.get(f"/api/v1/chat/conversations/{conversation['id']}").json()
    assistant = [m for m in detail["messages"] if m["role"] == "assistant"][-1]
    assert assistant["status"] == "failed"
    assert assistant["grounding_status"] == "retrieval_failed"
    assert assistant["retrieval_diagnostic_code"] == "embedding_unavailable"


def test_stream_client_disconnect_marks_failed_not_generating(db_session, fake_gateway):
    """P0.5-1: closing the SSE generator mid-stream (client disconnect) must not
    leave the assistant row stuck in "generating" forever."""
    from app.domains.chat.models import ChatMessage
    from app.domains.chat.service import ChatService

    service = ChatService(db_session, gateway=fake_gateway)
    events = service.stream_send_new("解释 GNN")
    for event in events:
        if event.get("type") == "token":
            break
    events.close()  # simulate the browser dropping the connection

    stuck = db_session.query(ChatMessage).filter_by(role="assistant", status="generating").all()
    assert stuck == []
    failed = db_session.query(ChatMessage).filter_by(role="assistant", status="failed").all()
    assert len(failed) == 1
    assert "中断" in failed[0].error_message


def test_stale_generating_row_is_healed_instead_of_bricking(db_session, fake_gateway):
    """P0.5-1: a "generating" row untouched for > STALE_GENERATING_SECONDS is
    marked failed on the next send instead of raising a permanent conflict."""
    from datetime import datetime, timedelta, timezone

    from app.domains.chat.models import ChatMessage
    from app.domains.chat.service import STALE_GENERATING_SECONDS, ChatService

    service = ChatService(db_session, gateway=fake_gateway)
    conversation = service.create_conversation("stale", None)

    def insert_generating(updated_at):
        message = ChatMessage(
            conversation_id=conversation.id,
            role="assistant",
            content="",
            status="generating",
            sequence=2,
        )
        db_session.add(message)
        db_session.commit()
        # updated_at is set by onupdate; force the stale timestamp explicitly.
        db_session.query(ChatMessage).filter(ChatMessage.id == message.id).update(
            {"updated_at": updated_at}
        )
        db_session.commit()
        return message

    fresh = insert_generating(datetime.now(timezone.utc))
    with pytest.raises(Exception) as conflict:
        list(service.stream_send(conversation.id, "再问一次"))  # generators run on iteration
    assert "already being generated" in str(conflict.value)
    db_session.delete(fresh)
    db_session.commit()

    insert_generating(
        datetime.now(timezone.utc) - timedelta(seconds=STALE_GENERATING_SECONDS + 60)
    )
    events = list(service.stream_send(conversation.id, "再问一次"))
    assert events[-1]["type"] == "done"
    statuses = [
        m.status
        for m in db_session.query(ChatMessage)
        .filter_by(conversation_id=conversation.id, role="assistant")
        .order_by(ChatMessage.sequence)
        .all()
    ]
    assert "generating" not in statuses
    assert statuses.count("failed") == 1  # the healed stale row
    assert statuses.count("completed") == 1  # the new answer
