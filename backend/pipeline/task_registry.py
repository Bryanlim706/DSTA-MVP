"""In-memory registry of running pipeline asyncio.Tasks keyed by job_id.

Tasks are registered when the pipeline starts and removed when complete,
errored, or cancelled. The terminate endpoint calls cancel() to force-abort
any in-flight awaitable (LLM call, port poll, etc.) immediately.
"""
from __future__ import annotations

import asyncio

_tasks: dict[str, asyncio.Task] = {}


def register(job_id: str, task: asyncio.Task) -> None:
    _tasks[job_id] = task


def cancel(job_id: str) -> bool:
    """Cancel the task for job_id. Returns True if a task was actually cancelled."""
    task = _tasks.pop(job_id, None)
    if task and not task.done():
        task.cancel()
        return True
    return False


def remove(job_id: str) -> None:
    _tasks.pop(job_id, None)
