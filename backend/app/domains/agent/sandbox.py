"""Docker-backed, opt-in validation for generated Python artifacts."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from app.core.config import settings
from app.domains.agent.models import AgentArtifact


class SandboxValidationError(RuntimeError):
    pass


def validate_python_artifacts(artifacts: list[AgentArtifact]) -> dict:
    if not settings.agent_code_execution_enabled:
        raise SandboxValidationError(
            "代码验证默认关闭；如需启用，请设置 AGENT_CODE_EXECUTION_ENABLED=true"
        )
    python_files = [item for item in artifacts if item.filename.endswith(".py")]
    if not python_files:
        return {"status": "skipped", "message": "没有 Python 文件需要验证"}
    with tempfile.TemporaryDirectory(prefix="gapmind-agent-") as temp_dir:
        root = Path(temp_dir).resolve()
        for artifact in artifacts:
            target = (root / artifact.filename).resolve()
            if root not in target.parents:
                raise SandboxValidationError("产物路径超出验证目录")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(artifact.content, encoding="utf-8")
        script = (
            "import pathlib,py_compile,sys;"
            "files=list(pathlib.Path('.').rglob('*.py'));"
            "errors=[];"
            "[(lambda p: py_compile.compile(str(p),doraise=True))(p) for p in files];"
            "print(f'validated {len(files)} python files')"
        )
        command = [
            settings.agent_docker_binary,
            "run", "--rm", "--pull", "never",
            "--network", "none",
            "--memory", settings.agent_sandbox_memory,
            "--cpus", str(settings.agent_sandbox_cpus),
            "--pids-limit", str(settings.agent_sandbox_pids),
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "-e", "PYTHONPYCACHEPREFIX=/tmp/pycache",
            "-v", f"{root}:/workspace:ro",
            "-w", "/workspace",
            settings.agent_sandbox_image,
            "python", "-c", script,
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=settings.agent_sandbox_timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise SandboxValidationError("找不到 Docker，请先安装并启动 Docker Desktop") from exc
        except subprocess.TimeoutExpired as exc:
            raise SandboxValidationError("隔离验证超时") from exc
        output = (completed.stdout + "\n" + completed.stderr).strip()[:8000]
        return {
            "status": "passed" if completed.returncode == 0 else "failed",
            "exit_code": completed.returncode,
            "output": output,
            "image": settings.agent_sandbox_image,
        }
