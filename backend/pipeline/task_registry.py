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


def launch(job_id: str, coro) -> asyncio.Task:
    """Create + register a pipeline task that auto-deregisters when it finishes.

    Single launch path for every step chain so terminate's cancel(job_id) can
    force-abort the in-flight await. Replaces FastAPI BackgroundTasks, whose tasks
    are unregistered and not cancellable. The done-callback only clears the slot if
    it still points at this task (a newer launch for the same job_id may replace it).
    """
    task = asyncio.create_task(coro)
    _tasks[job_id] = task
    task.add_done_callback(
        lambda t: _tasks.pop(job_id, None) if _tasks.get(job_id) is t else None
    )
    return task


def cancel(job_id: str) -> bool:
    """Cancel the task for job_id. Returns True if a task was actually cancelled."""
    task = _tasks.pop(job_id, None)
    if task and not task.done():
        task.cancel()
        return True
    return False


def remove(job_id: str) -> None:
    _tasks.pop(job_id, None)
