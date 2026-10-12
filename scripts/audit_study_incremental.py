"""Audit completed immutable traces while a long paired study is still running."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.audit_research_trace import audit_manifest


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def trace_binding(path):
    path=Path(path);m=json.loads(path.read_bytes())
    return {'manifest_sha256':digest(path),'event_sha256':digest(m['event_file']),
            'metrics_sha256':digest(path.parent/'metrics.json'),
            'configuration_file_sha256':digest(m['configuration_file']),
            'auditor_sha256':digest(ROOT/'scripts/audit_research_trace.py'),
            'invariants_sha256':digest(ROOT/'rts_predictive/simulator/research_audit.py'),
            'projection_sha256':digest(ROOT/'rts_predictive/dashboard/research_projection.py'),
            'runtime_evidence_auditor_sha256':digest(ROOT/'rts_predictive/simulator/runtime_evidence_audit.py')}


def cached_audit(path,cache):
    binding=trace_binding(path);target=Path(cache)/(binding['manifest_sha256']+'.json')
    if target.exists():
        saved=json.loads(target.read_bytes())
        if saved['binding']==binding and saved['audit']['status']=='PASS':return saved['audit']
    audit=audit_manifest(path);assert audit['status']=='PASS'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps({'binding':binding,'audit':audit},indent=2),encoding='utf-8')
    return audit


def main():
    p=argparse.ArgumentParser();p.add_argument('study');p.add_argument('--cache',required=True)
    p.add_argument('--pairs',type=int,required=True);p.add_argument('--timeout-seconds',type=int,default=3600)
    a=p.parse_args();root=Path(a.study);seen=set();start=time.monotonic()
    while len(seen)<2*a.pairs:
        for path in sorted(root.glob('*/*/manifest.json')):
            if path in seen:continue
            m=json.loads(path.read_bytes())
            if m['status']!='COMPLETE':continue
            cached_audit(path,a.cache);seen.add(path)
            print(f'PASS completed trace {len(seen)}/{2*a.pairs}: {m["family"]} {m["seed"]} {m["policy"]}',flush=True)
        if time.monotonic()-start>a.timeout_seconds:raise TimeoutError('study did not complete within the audit window')
        if len(seen)<2*a.pairs:time.sleep(1)
    print(json.dumps({'status':'PASS','policy_traces':len(seen),'cache':str(Path(a.cache).resolve())}),flush=True)


if __name__=='__main__':main()
