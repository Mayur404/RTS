"""Deleting a session cannot let an already-looked-up request write after close."""
import hashlib
import json
import threading

import pytest
from fastapi import HTTPException

from rts_predictive.api import research
from rts_predictive.domain.research import default_research_config


def test_closed_session_rejects_step_before_mutating_time_or_evidence(tmp_path):
    session = research.PairedResearchSession(default_research_config(release_end_us=100_000), tmp_path)
    session.step(1000)
    session.close()
    at = session.engines[session.baseline].now
    counts = {p: len(e.events) for p,e in session.engines.items()}
    digests = {p: hashlib.sha256((session.root/p/'events.jsonl').read_bytes()).hexdigest()
               for p in session.engines}
    with pytest.raises(research.ResearchSessionClosedError):
        session.step(1000)
    session.close()  # Closure is idempotent.
    assert session.engines[session.baseline].now == at
    assert {p:len(e.events) for p,e in session.engines.items()} == counts
    for policy,digest in digests.items():
        assert hashlib.sha256((session.root/policy/'events.jsonl').read_bytes()).hexdigest() == digest
        manifest = json.loads((session.root/policy/'manifest.json').read_text())
        assert manifest['status'] == 'INTERRUPTED' and manifest['event_sha256'] == digest


def test_step_request_that_races_deletion_returns_existing_not_found_status(tmp_path,monkeypatch):
    session = research.PairedResearchSession(default_research_config(release_end_us=100_000), tmp_path)
    session.close()
    monkeypatch.setattr(research,'lookup',lambda uid:session)
    with pytest.raises(HTTPException) as caught:
        research.step(session.id,research.ResearchStep(delta_us=1000))
    assert caught.value.status_code == 404
    assert session.engines[session.baseline].now == 0


def test_close_waits_for_in_flight_step_and_then_preserves_its_trace(tmp_path,monkeypatch):
    session = research.PairedResearchSession(default_research_config(release_end_us=100_000), tmp_path)
    entered, release, closing, closed = [threading.Event() for _ in range(4)]
    errors = []
    engine = session.engines[session.baseline]
    original = engine.run_until
    def held_step(at):
        entered.set()
        if not release.wait(5):raise RuntimeError('test release timed out')
        return original(at)
    monkeypatch.setattr(engine,'run_until',held_step)
    def advance():
        try:session.step(1000)
        except Exception as exc:errors.append(exc)
    def close():
        closing.set()
        try:session.close()
        except Exception as exc:errors.append(exc)
        finally:closed.set()
    stepping = threading.Thread(target=advance)
    deleting = threading.Thread(target=close)
    stepping.start()
    try:
        assert entered.wait(5)
        deleting.start()
        assert closing.wait(5)
        assert not closed.is_set()
    finally:
        release.set()
        stepping.join(5)
        if deleting.ident is not None:deleting.join(5)
        session.close()
    assert not errors and closed.is_set()
    assert all(e.now == 1000 for e in session.engines.values())
    for policy in session.engines:
        manifest = json.loads((session.root/policy/'manifest.json').read_text())
        assert manifest['status'] == 'INTERRUPTED'
        assert manifest['event_count'] == len(session.engines[policy].events)
