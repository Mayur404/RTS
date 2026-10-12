"""Bind recorded watchdog windows to their actual conditional fallback analysis."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rts_predictive.artifacts.events import iter_canonical_events


def audit_watchdog_observations(events):
    analyses={};observations={};aborts={};checks=0;bounded=0;recoveries=0
    for event in events:
        kind=event['event_type'];p=event['payload'];tid=event.get('task_id');aid=event.get('attempt_id')
        if kind=='FALLBACK_ANALYSIS':analyses[tid]=p
        elif kind=='WATCHDOG_CHECK':
            checks+=1;certificate=analyses.get(tid)
            if p['recovery_bound_us'] is not None:
                if not certificate or certificate['status']!='VERIFIED' or certificate['at_us']!=event['timestamp_us'] or certificate['response_bound_us']!=p['recovery_bound_us']:
                    raise ValueError('watchdog recovery bound lacks matching conditional certificate')
                bounded+=1
            observations[aid]=(event,certificate)
        elif kind=='WATCHDOG_ABORT':
            observation,certificate=observations.get(aid,(None,None))
            if not observation or observation['timestamp_us']!=event['timestamp_us'] or observation['payload']['action']!='ABORT' or not certificate or certificate['status']!='VERIFIED':
                raise ValueError('watchdog abort lacks its admitted recovery analysis')
            aborts[tid]=(event,certificate)
        elif kind=='FALLBACK_ADMITTED' and tid in aborts:
            abort,certificate=aborts.pop(tid)
            if event['timestamp_us']!=abort['timestamp_us'] or p['certificate_sha256']!=certificate['certificate_sha256'] or p['response_bound_us']!=certificate['response_bound_us']:
                raise ValueError('watchdog admission differs from its recovery analysis')
            recoveries+=1
    if aborts:raise ValueError('watchdog abort has no local fallback admission')
    return {'schema_version':'watchdog-observation-audit/1.0','status':'PASS','watchdog_checks':checks,'checks_with_conditional_bounds':bounded,'matched_recovery_admissions':recoveries,
            'scope':'recorded simulator watchdog bounds and admissions; conditional assumptions preserved; not physical safety'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('manifests',nargs='+');parser.add_argument('--output',required=True)
    args=parser.parse_args();reports=[]
    for name in args.manifests:
        path=Path(name);manifest=json.loads(path.read_bytes())
        event_hash=hashlib.sha256(Path(manifest['event_file']).read_bytes()).hexdigest()
        if event_hash!=manifest['event_sha256']:raise ValueError('raw event checksum differs from manifest')
        report=audit_watchdog_observations(iter_canonical_events(manifest['event_file'],expected_run_id=manifest['run_id']))
        reports.append({'manifest':str(path.resolve()),'manifest_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                        'event_sha256':event_hash,'checker_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                        'source_sha256':manifest['source_sha256'],**report})
    Path(args.output).write_text(json.dumps(reports,indent=2),encoding='utf-8')
    print(json.dumps({'status':'PASS','traces':len(reports),'watchdog_checks':sum(r['watchdog_checks'] for r in reports),'matched_recovery_admissions':sum(r['matched_recovery_admissions'] for r in reports)}))


if __name__=='__main__':main()
