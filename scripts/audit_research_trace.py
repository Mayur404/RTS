"""Audit actual run manifests and raw traces without regenerating old evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rts_predictive.artifacts.events import iter_canonical_events
from rts_predictive.simulator.research_audit import audit_research_events
from rts_predictive.dashboard.research_projection import ResearchProjection
from rts_predictive.domain.serialization import canonical_sha256


def audit_manifest(filename):
    path = Path(filename); raw = path.read_bytes(); manifest = json.loads(raw)
    configuration = json.loads(Path(manifest['configuration_file']).read_bytes())
    if canonical_sha256(configuration) != manifest['configuration_hash']: raise ValueError('configuration checksum mismatch')
    event_path = Path(manifest['event_file'])
    event_hash = hashlib.sha256(event_path.read_bytes()).hexdigest()
    if event_hash != manifest['event_sha256']: raise ValueError('raw event checksum mismatch')
    report = audit_research_events(iter_canonical_events(event_path, expected_run_id=manifest['run_id']),
                                   devices=configuration['devices'])
    if report['canonical_events'] != manifest['event_count']: raise ValueError('event count mismatch')
    projection = ResearchProjection()
    for e in iter_canonical_events(event_path): projection.consume(e)
    metric_file = path.parent/'metrics.json'; metric_raw = metric_file.read_bytes()
    if hashlib.sha256(metric_raw).hexdigest() != manifest['metrics_sha256']: raise ValueError('metric checksum mismatch')
    if projection.metrics() != json.loads(metric_raw): raise ValueError('current projection differs from archived metrics')
    report.update(manifest_file=str(path.resolve()),manifest_sha256=hashlib.sha256(raw).hexdigest(),
                  event_sha256=event_hash,configuration_hash=manifest['configuration_hash'],
                  source_sha256=manifest['source_sha256'],evidence='SIMULATED')
    report['auditor_sha256']=hashlib.sha256((Path(__file__).resolve().parents[1]/'rts_predictive/simulator/research_audit.py').read_bytes()).hexdigest()
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('manifests',nargs='+');parser.add_argument('--output')
    args=parser.parse_args();reports=[audit_manifest(p) for p in args.manifests]
    text=json.dumps(reports,indent=2)
    if args.output:
        path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8')
    print(text)


if __name__=='__main__':main()
