"""Assessment run state machine: legal/illegal transitions (fake DB).

Run: uv run pytest src/testing/test_assessment_state_machine.py
"""

import pytest

from src.assessments.runner import (
    _ALLOWED_TRANSITIONS,
    ACTIVE_STATUSES,
    AssessmentRunner,
    InvalidTransitionError,
    TERMINAL_STATUSES,
)


# ---------------------------------------------------------------------------
# Transition map semantics
# ---------------------------------------------------------------------------

def test_happy_path_is_legal():
    path = ["draft", "queued", "collecting", "evaluating", "completed"]
    for src, dst in zip(path, path[1:]):
        assert dst in _ALLOWED_TRANSITIONS[src], f"{src} -> {dst} must be legal"


def test_cancel_legal_from_every_active_state():
    for status in ACTIVE_STATUSES:
        assert "cancelled" in _ALLOWED_TRANSITIONS[status]


def test_reevaluate_only_from_completed_states():
    assert "evaluating" in _ALLOWED_TRANSITIONS["completed"]
    assert "evaluating" in _ALLOWED_TRANSITIONS["completed_with_errors"]
    for terminal in ("failed", "cancelled"):
        assert terminal not in _ALLOWED_TRANSITIONS  # no exits from failed/cancelled


def test_no_skipping_phases():
    assert "completed" not in _ALLOWED_TRANSITIONS["draft"]
    assert "evaluating" not in _ALLOWED_TRANSITIONS["draft"]
    assert "completed" not in _ALLOWED_TRANSITIONS["queued"]


def test_terminal_states_are_consistent():
    assert set(TERMINAL_STATUSES) == {"completed", "completed_with_errors",
                                      "failed", "cancelled"}


# ---------------------------------------------------------------------------
# transition() against a fake session
# ---------------------------------------------------------------------------

class _Run:
    def __init__(self, status):
        self.status = status


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    def __init__(self, run):
        self.run = run
        self.updates = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, stmt):
        if stmt.is_select:
            return _FakeResult(self.run)
        self.updates.append(stmt.compile().params)
        return _FakeResult(None)

    async def commit(self):
        pass


def _patch_session(monkeypatch, run):
    session = _FakeSession(run)
    import src.core.database as db_mod
    monkeypatch.setattr(db_mod, "async_session_factory", lambda: session)
    return session


async def test_transition_updates_status(monkeypatch):
    session = _patch_session(monkeypatch, _Run("draft"))
    await AssessmentRunner("r1", "acme").transition("queued")
    assert session.updates and session.updates[0]["status"] == "queued"


async def test_illegal_transition_raises(monkeypatch):
    _patch_session(monkeypatch, _Run("draft"))
    with pytest.raises(InvalidTransitionError, match="illegal transition"):
        await AssessmentRunner("r1", "acme").transition("completed")


async def test_transition_from_terminal_raises(monkeypatch):
    _patch_session(monkeypatch, _Run("cancelled"))
    with pytest.raises(InvalidTransitionError):
        await AssessmentRunner("r1", "acme").transition("queued")


async def test_terminal_transition_sets_finished_at(monkeypatch):
    session = _patch_session(monkeypatch, _Run("evaluating"))
    await AssessmentRunner("r1", "acme").transition("completed_with_errors")
    params = session.updates[0]
    assert params["status"] == "completed_with_errors"
    assert params.get("finished_at") is not None


async def test_missing_run_raises(monkeypatch):
    _patch_session(monkeypatch, None)
    with pytest.raises(InvalidTransitionError, match="not found"):
        await AssessmentRunner("ghost", "acme").transition("queued")
