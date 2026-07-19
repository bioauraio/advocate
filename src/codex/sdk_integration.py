"""Compatibility adapter: Codex CLI behind the existing ClaudeIntegration API."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import structlog

from ..claude.exceptions import ClaudeProcessError, ClaudeTimeoutError
from ..claude.sdk_integration import ClaudeResponse, StreamUpdate
from ..config.settings import Settings

logger = structlog.get_logger()


class CodexSDKManager:
    """Runs ``codex exec --json`` while preserving the bot's response contract."""

    def __init__(self, config: Settings):
        self.config = config
        self.binary = os.environ.get("CODEX_BINARY", "codex")

    async def execute_command(
        self,
        prompt: str,
        working_directory: Path,
        session_id: Optional[str] = None,
        continue_session: bool = False,
        stream_callback: Optional[Callable] = None,
        interrupt_event: Optional[asyncio.Event] = None,
        images: Optional[List[Dict[str, str]]] = None,
        permission_mode: Optional[str] = None,
    ) -> ClaudeResponse:
        del permission_mode  # Lawyer bot is intentionally read-only.
        started = time.monotonic()

        if continue_session and session_id:
            command = [
                self.binary,
                "exec",
                "resume",
                "--json",
                "--skip-git-repo-check",
                session_id,
                "-",
            ]
        else:
            command = [
                self.binary,
                "exec",
                "--json",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--color",
                "never",
                "-C",
                str(working_directory),
            ]
            for image in images or []:
                path = image.get("path") or image.get("file_path")
                if path and Path(path).is_file():
                    command.extend(["--image", path])
            command.append("-")

        env = os.environ.copy()
        env.setdefault("HOME", "/root")
        env.setdefault("CODEX_HOME", "/root/.codex")
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(working_directory),
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert process.stdin and process.stdout and process.stderr
        process.stdin.write(prompt.encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()

        thread_id = session_id or ""
        messages: List[str] = []
        tools_used: List[Dict[str, object]] = []
        usage: Dict[str, int] = {}
        interrupted = False

        async def consume() -> None:
            nonlocal thread_id, usage
            while line := await process.stdout.readline():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type")
                if event_type == "thread.started":
                    thread_id = str(event.get("thread_id") or thread_id)
                elif event_type == "item.completed":
                    item = event.get("item") or {}
                    item_type = item.get("type")
                    if item_type == "agent_message" and item.get("text"):
                        text = str(item["text"]).strip()
                        if text:
                            messages.append(text)
                            if stream_callback:
                                result = stream_callback(StreamUpdate(type="assistant", content=text))
                                if inspect.isawaitable(result):
                                    await result
                    elif item_type in {"command_execution", "mcp_tool_call", "web_search"}:
                        tools_used.append(
                            {
                                "name": str(item_type),
                                "timestamp": time.time(),
                                "input": {"status": item.get("status")},
                            }
                        )
                elif event_type == "turn.completed":
                    raw_usage = event.get("usage") or {}
                    usage = {key: int(value or 0) for key, value in raw_usage.items()}

        consume_task = asyncio.create_task(consume())
        interrupt_task = (
            asyncio.create_task(interrupt_event.wait()) if interrupt_event is not None else None
        )
        try:
            if interrupt_task is None:
                await asyncio.wait_for(consume_task, timeout=self.config.claude_timeout_seconds)
            else:
                done, _ = await asyncio.wait(
                    {consume_task, interrupt_task},
                    timeout=self.config.claude_timeout_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if interrupt_task in done and interrupt_event and interrupt_event.is_set():
                    interrupted = True
                    process.terminate()
                    consume_task.cancel()
                elif consume_task not in done:
                    raise asyncio.TimeoutError
            return_code = await process.wait()
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise ClaudeTimeoutError(
                f"Codex CLI timed out after {self.config.claude_timeout_seconds}s"
            ) from exc
        finally:
            if interrupt_task is not None:
                interrupt_task.cancel()

        stderr = (await process.stderr.read()).decode("utf-8", errors="replace").strip()
        if return_code != 0 and not interrupted:
            safe_error = stderr[-1000:] if stderr else f"exit code {return_code}"
            raise ClaudeProcessError(f"Codex CLI failed: {safe_error}")

        content = messages[-1] if messages else ""
        return ClaudeResponse(
            content=content,
            session_id=thread_id,
            cost=0.0,
            duration_ms=int((time.monotonic() - started) * 1000),
            num_turns=1,
            is_error=return_code != 0,
            tools_used=tools_used,
            interrupted=interrupted,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=usage.get("cached_input_tokens", 0),
            cache_creation_tokens=0,
        )
