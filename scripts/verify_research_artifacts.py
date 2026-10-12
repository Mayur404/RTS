"""Reconcile publication aggregates with archived canonical event evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rts_predictive.artifacts.events import iter_canonical_events
from rts_predictive.dashboard.research_projection import ResearchProjection,paired_comparison


def main():
    p=argparse.ArgumentParser();p.add_argument('aggregates',nargs='+');a=p.parse_args()
    runs=0;count=0;source_hashes=set();models=set()
    for filename in a.aggregates:
        aggregate=json.loads(Path(filename).read_text(encoding='utf-8'))
        for row in aggregate['pairs']:
            metrics={};config_hashes=set()
            for policy,ref in row['manifest_files'].items():
                path=Path(ref['path']);raw=path.read_bytes();manifest=json.loads(raw)
                assert hashlib.sha256(raw).hexdigest()==ref['sha256'],path
                assert manifest['status']=='COMPLETE'
                source_hashes.add(manifest['source_sha256'])
                config_hashes.add(manifest['configuration_hash'])
                if manifest['models']:models.add(manifest['models']['gnn_sha256'])
                events=Path(manifest['event_file'])
                assert hashlib.sha256(events.read_bytes()).hexdigest()==manifest['event_sha256']
                projection=ResearchProjection();committed=set();planned={};event_count=0
                for event in iter_canonical_events(events,expected_run_id=manifest['run_id']):
                    projection.consume(event);event_count+=1
                    kind,tid=event['event_type'],event.get('task_id')
                    if kind=='TASK_PLANNED':planned[tid]=event['payload']['parents']
                    if kind=='TASK_READY':assert all(parent in committed for parent in planned[tid])
                    if kind=='TASK_COMMIT':
                        assert tid not in committed,'multiple committed results'
                        assert event['timestamp_us']<=projection.tasks[tid]['deadline_us']
                        committed.add(tid)
                metric_path=path.parent/'metrics.json';metric_raw=metric_path.read_bytes()
                assert hashlib.sha256(metric_raw).hexdigest()==manifest['metrics_sha256']
                metrics[policy]=projection.metrics()
                assert metrics[policy]==json.loads(metric_raw)
                assert metrics[policy]['final'] and not metrics[policy]['pending_jobs']
                assert event_count==manifest['event_count']
                archive=path.parent.parent/'source.zip'
                assert hashlib.sha256(archive.read_bytes()).hexdigest()==manifest['source_archive_sha256']
                runs+=1;count+=event_count
            assert len(config_hashes)==1
            comparison=paired_comparison(metrics[aggregate.get('baseline','edf')],metrics['protected'])
            assert all(comparison[k]==row[k] for k in comparison)
            assert metrics[aggregate.get('baseline','edf')]==row['before']
            assert metrics['protected']==row['after']
        # Verify reported family means, without merging families or engine versions.
        for family,g in aggregate['groups'].items():
            rows=[r for r in aggregate['pairs'] if r['family']==family]
            assert len(rows)==g['paired_seeds']
            assert sum(r['change_pp'] for r in rows)/len(rows)==g['mean_change_pp']
    print(json.dumps({'reconciled_artifact_runs':runs,'canonical_events':count,
                      'source_versions':len(source_hashes),'gnn_versions':len(models)}))


if __name__=='__main__':main()
