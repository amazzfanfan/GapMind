"""Chat API tests use a fake gateway and never call DeepSeek."""

from __future__ import annotations

from dataclasses import dataclass

import pytest


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


@pytest.fixture
def fake_gateway(monkeypatch):
    gateway = FakeGateway()
    monkeypatch.setattr("app.domains.chat.service.get_llm_gateway", lambda: gateway)
    return gateway


def test_first_send_creates_conversation_and_two_messages(client, fake_gateway):
    response = client.post("/api/v1/chat/conversations/send", json={"content": "  什么是时间图神经网络？  "})

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

    assert client.delete(f"/api/v1/chat/conversations/{first['conversation']['id']}").json()["deleted"] is True
    assert client.get(f"/api/v1/chat/conversations/{first['conversation']['id']}").status_code == 404
    assert client.post(
        f"/api/v1/chat/conversations/{first['conversation']['id']}/messages",
        json={"content": "不能继续"},
    ).status_code == 404


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
    retry = client.post(f"/api/v1/chat/conversations/{conversation_id}/messages/{assistant_id}/retry")
    assert retry.status_code == 200
    assert retry.json()["assistant_message"]["status"] == "completed"
    assert len(fake_gateway.calls) == 2

    assert client.post(f"/api/v1/chat/conversations/{conversation_id}/messages/{assistant_id}/retry").status_code == 409


def test_missing_api_key_is_mapped_to_503_and_persisted(client, fake_gateway):
    fake_gateway.api_key = ""
    response = client.post("/api/v1/chat/conversations/send", json={"content": "测试未配置密钥"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == "deepseek_unavailable"
    messages = client.get(f"/api/v1/chat/conversations/{detail['conversation_id']}").json()["messages"]
    assert messages[-1]["status"] == "failed"


def test_validation_and_generating_conflict(client, db_session, fake_gateway):
    assert client.post("/api/v1/chat/conversations/send", json={"content": "   "}).status_code == 422
    assert client.post("/api/v1/chat/conversations/send", json={"content": "x" * 12001}).status_code == 400

    created = client.post("/api/v1/chat/conversations", json={}).json()
    # Insert a real generating message through the public model fixture path.
    from app.db.models import ChatMessage

    db_session.add(ChatMessage(conversation_id=created["id"], role="assistant", content="", status="generating", sequence=1))
    db_session.commit()

    response = client.post(
        f"/api/v1/chat/conversations/{created['id']}/messages",
        json={"content": "重复发送"},
    )
    assert response.status_code == 409
