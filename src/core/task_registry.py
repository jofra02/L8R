"""In-process registry of running asyncio Tasks keyed by run_id.

Used to cancel running LangGraph pipelines from the API.
"""
import asyncio
from typing import Dict

_running_tasks: Dict[str, asyncio.Task] = {}


def register(run_id: str, task: asyncio.Task):
    _running_tasks[run_id] = task


def unregister(run_id: str):
    _running_tasks.pop(run_id, None)


def cancel(run_id: str) -> bool:
    task = _running_tasks.get(run_id)
    if task and not task.done():
        task.cancel()
        return True
    return False


def is_running(run_id: str) -> bool:
    task = _running_tasks.get(run_id)
    return task is not None and not task.done()
