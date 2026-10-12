"""Write a paper-facing summary from finalized, checksummed paired artifacts."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics


def main():
    p=argparse.ArgumentParser();p.add_argument('aggregates',nargs='+')
    p.add_argument('--output',default='.validation/final-summary');a=p.parse_args()
    root=Path(a.output);root.mkdir(parents=True,exist_ok=True)
    rows=[];sources=[];overhead=[];total_events=0;watchdogs=0;publications=0;inferences=0
    for filename in a.aggregates:
        path=Path(filename);data=json.loads(path.read_text(encoding='utf-8'))
        sources.append({'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        for family,g in data['groups'].items():
            rows.append({'family':family,**g})
        for pair in data['pairs']:
            protected=pair['after'];watchdogs+=protected['watchdog_aborts'];publications+=protected['model_publications'];inferences+=protected['gnn_inferences']
            for ref in pair['manifest_files'].values():
                raw=Path(ref['path']).read_bytes();assert hashlib.sha256(raw).hexdigest()==ref['sha256']
                manifest=json.loads(raw);total_events+=manifest['event_count']
            ref=pair['manifest_files']['protected'];manifest_path=Path(ref['path'])
            deadlines={}
            with (manifest_path.parent/'events.jsonl').open(encoding='utf-8') as f:
                for line in f:
                    event=json.loads(line)
                    if event['event_type']=='TASK_READY':deadlines[event['task_id']]=event['payload']['deadline_us']
            host=json.loads((manifest_path.parent/'host.json').read_text(encoding='utf-8'))
            for observation in host['observations']:
                if observation['kind']!='gnn':continue
                slack=deadlines[observation['task']]-observation['at_us']
                overhead.append({'latency_us':observation['latency_us'],'modeled_remaining_slack_us':slack,
                                 'host_latency_over_modeled_slack':observation['latency_us']/slack if slack>0 else None})
    latencies=sorted(v['latency_us'] for v in overhead)
    host={'evidence':'MEASURED_ON_HOST','inference_count':len(latencies),'mean_us':statistics.mean(latencies) if latencies else None,
          'p95_us':latencies[int(.95*(len(latencies)-1))] if latencies else None,
          'note':'Concurrent experiment execution can affect host latency. This is not a WCET or modeled service budget.'}
    result={'schema_version':'research-paper-summary/1.0','evidence':'SIMULATED','sources':sources,'groups':rows,
            'canonical_event_count':total_events,'watchdog_recoveries':watchdogs,'model_publications':publications,
            'gnn_inferences':inferences,'host_inference':host}
    (root/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    (root/'host-overhead.json').write_text(json.dumps(overhead),encoding='utf-8')
    lines=['# Recorded simulation results','',
           'Primary endpoint: end-to-end job deadline misses / all released jobs after drain.',
           'Same releases, demands and configured interference are paired by seed. Each family is analyzed separately.','',
           '| Scenario | Paired seeds | EDF misses (%) | Protected misses (%) | Change (pp) | Paired bootstrap 95% CI (pp) | Regressed seeds |',
           '|---|---:|---:|---:|---:|---|---:|']
    for r in rows:
        ci=r['paired_bootstrap_95_ci_pp'];interval=f'[{ci[0]:.3f}, {ci[1]:.3f}]' if ci else 'undefined'
        lines.append(f"| {r['family']} | {r['paired_seeds']} | {r['mean_before_pct']:.3f} | {r['mean_after_pct']:.3f} | {r['mean_change_pp']:.3f} | {interval} | {r['regressed_seeds']} |")
    lines+=['',f'Recorded {total_events:,} canonical events, {inferences:,} real GNN calls, {watchdogs:,} watchdog recovery starts and {publications:,} federated publications in the protected runs.',
            '', 'These are scenario-specific simulated outcomes. Nominal zero misses do not prove schedulability. Exact RTA applies only to the separately bound hypothetical reference partition.',
            'The smaller baseline pilots include a regime where unconditional offload outperformed protection. No across-baseline superiority claim follows.',
            'Configured service budgets, thermal dynamics and output utility require independent validation. See docs/research_methods.md.',
            '', '## Source aggregates','']
    lines += [f"- `{s['path']}` (SHA-256 `{s['sha256']}`)" for s in sources]
    (root/'results.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
