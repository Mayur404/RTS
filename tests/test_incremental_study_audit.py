"""Cache integrity contract fixtures; these are not experimental evidence."""
import json
from pathlib import Path
import pytest
from scripts import audit_study_incremental as module


@pytest.fixture
def trace_fixture(tmp_path,monkeypatch):
    monkeypatch.setattr(module,'ROOT',tmp_path)
    paths=['scripts/audit_research_trace.py','rts_predictive/simulator/research_audit.py',
           'rts_predictive/dashboard/research_projection.py','rts_predictive/simulator/runtime_evidence_audit.py',
           'pair/edf/events.jsonl','pair/edf/metrics.json','pair/config.json']
    for name in paths:
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('contract fixture',encoding='utf-8')
    path=tmp_path/'pair/edf/manifest.json'
    path.write_text(json.dumps({'event_file':str(tmp_path/'pair/edf/events.jsonl'),
                                'configuration_file':str(tmp_path/'pair/config.json')}),encoding='utf-8')
    calls=[]
    def audit(p):
        calls.append(Path(p));return {'status':'PASS','fixture_only':True}
    monkeypatch.setattr(module,'audit_manifest',audit)
    return tmp_path,path,calls


def test_unchanged_files_and_auditor_reuse_the_completed_trace_audit(trace_fixture):
    root,path,calls=trace_fixture
    first=module.cached_audit(path,root/'cache')
    assert module.cached_audit(path,root/'cache')==first
    assert calls==[path]


@pytest.mark.parametrize('changed',['pair/edf/events.jsonl','pair/edf/metrics.json','scripts/audit_research_trace.py'])
def test_modified_raw_evidence_or_auditor_cannot_inherit_a_passing_cache(trace_fixture,changed,monkeypatch):
    root,path,calls=trace_fixture
    module.cached_audit(path,root/'cache');assert len(calls)==1
    (root/changed).write_text('changed contract fixture',encoding='utf-8')
    def reject(_):raise ValueError('fresh audit rejected changed fixture')
    monkeypatch.setattr(module,'audit_manifest',reject)
    with pytest.raises(ValueError,match='fresh audit rejected'):
        module.cached_audit(path,root/'cache')
