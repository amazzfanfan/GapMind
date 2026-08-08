"""The optional validator must keep generated code inside a restricted container."""

from __future__ import annotations

from types import SimpleNamespace

from app.core.config import settings
from app.domains.agent.models import AgentArtifact
from app.domains.agent.sandbox import validate_python_artifacts


def test_sandbox_validation_uses_no_network_and_resource_limits(monkeypatch):
    captured: dict = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="validated 1 python files", stderr="")

    monkeypatch.setattr(settings, "agent_code_execution_enabled", True)
    monkeypatch.setattr("app.domains.agent.sandbox.subprocess.run", fake_run)
    artifact = AgentArtifact(
        run_id="run-1", artifact_type="code", filename="src/train.py",
        mime_type="text/x-python", content="print('ok')", metadata_payload={},
        validation_status="not_run", is_deleted=False,
    )
    result = validate_python_artifacts([artifact])
    command = captured["command"]
    assert result["status"] == "passed"
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert command[command.index("--pull") + 1] == "never"
    assert "--cap-drop" in command
    assert "--memory" in command
    assert captured["kwargs"]["timeout"] == settings.agent_sandbox_timeout_seconds
