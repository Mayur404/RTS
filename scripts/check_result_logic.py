"""Audit plain results against fresh raw traces and independently replay models."""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from rts_predictive.api.research import PairedResearchSession
from rts_predictive.api.scenario_designer import template,ScenarioInput
from scripts.audit_research_trace import audit_manifest
from scripts.verify_runtime_end_to_end import replay_models


def js(source,setup,expression):
    out=subprocess.run([shutil.which('node')],input=source+'\n'+setup+'\nconsole.log(JSON.stringify('+expression+'));',check=True,capture_output=True,text=True)
    return json.loads(out.stdout)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    args=parser.parse_args();root=Path(args.output)
    if (root/'report.json').exists():parser.error('use a fresh output directory')
    root.mkdir(parents=True,exist_ok=True)
    config_source=(ROOT/'frontend/ground-map.js').read_text(encoding='utf-8').split('function configureGroundScenario',1)[1]
    config_source='function configureGroundScenario'+config_source
    summary_source=(ROOT/'frontend/plain-results.js').read_text(encoding='utf-8')
    cases=[(family,6,'mixed',100,False) for family in ['nominal','bursty','thermal','unreliable']]
    cases += [('unreliable',6,'mixed',100,True),('unreliable',8,'mixed',150,True),('nominal',2,'control',50,False),('nominal',8,'telemetry',150,False)]
    reports=[]
    for family,count,mix,rate,stress in cases:
        scenario=js(config_source,'const t='+json.dumps(template(family))+';',f'configureGroundScenario(t,{count},{json.dumps(mix)},{rate},{json.dumps(stress)})')
        config,_=ScenarioInput.model_validate(scenario).compile()
        session=PairedResearchSession(config,root/'runs',custom_scenario=True)
        try:
            x=session.step(config.end_us)
            summary=js(summary_source,'const x='+json.dumps(x)+';','deriveResultSummary(x)')
            assert not summary['issues'],summary['issues']
            audits={};replays={};raw_jobs={}
            for policy,engine in session.engines.items():
                audits[policy]=audit_manifest(session.root/policy/'manifest.json')
                replays[policy]=replay_models(engine)
                jobs={}
                for e in engine.events:
                    if e['event_type']=='JOB_RELEASE':jobs[e['job_id']]={'release':e['timestamp_us'],'deadline':e['payload']['deadline_us'],'state':'ACTIVE'}
                    elif e['event_type'] in ['JOB_COMPLETE','JOB_MISS']:jobs[e['job_id']].update(state='COMPLETE' if e['event_type']=='JOB_COMPLETE' else 'MISSED',terminal=e['timestamp_us'])
                raw_jobs[policy]=jobs
                done=[j for j in jobs.values() if j['state']=='COMPLETE']
                expected_mean=sum(j['terminal']-j['release'] for j in done)/len(done) if done else None
                assert summary['timing']['after' if policy=='protected' else 'before']['mean_us']==expected_mean
                assert all(j['terminal']<=j['deadline'] for j in done)
            paired=Counter()
            assert raw_jobs['edf'].keys()==raw_jobs['protected'].keys()
            for id,a in raw_jobs['edf'].items():
                b=raw_jobs['protected'][id]
                paired['both_met' if a['state']==b['state']=='COMPLETE' else 'both_missed' if a['state']==b['state']=='MISSED' else 'rescued' if b['state']=='COMPLETE' else 'regressed']+=1
            for key in ['both_met','both_missed','rescued','regressed']:assert summary['paired'][key]==paired[key]
            protected=session.engines['protected'];counts=Counter(e['event_type'] for e in protected.events)
            admitted={e['task_id'] for e in protected.events if e['event_type']=='FALLBACK_ADMITTED'}
            committed={e['task_id'] for e in protected.events if e['event_type']=='TASK_COMMIT'}
            missed={e['task_id'] for e in protected.events if e['event_type']=='TASK_DEADLINE'}
            skipped={e['task_id'] for e in protected.events if e['event_type']=='TASK_SKIPPED'}
            assert summary['recovery']['tasks']==len(admitted)
            assert summary['recovery']['finished']==len(admitted&committed)
            assert summary['recovery']['missed']==len(admitted&missed)
            assert summary['recovery']['skipped']==len(admitted&skipped)
            assert summary['recovery']['pending']==0
            assert x['after']['metrics']['watchdog_aborts']==counts['WATCHDOG_ABORT']
            assert x['after']['metrics']['early_exits']==counts['EARLY_EXIT']
            reports.append({'family':family,'devices':count,'mix':mix,'rate':rate,'stress':stress,'session_id':session.id,'configuration_hash':config.config_hash,'summary':summary,'metrics':{'baseline':x['before']['metrics'],'protected':x['after']['metrics']},'audits':audits,'model_replays':replays})
            print(f'PASS {len(reports)}/{len(cases)}: {family}, {count} devices, {mix}, {rate}%, stress={stress}',flush=True)
        finally:session.close()
    (root/'report.json').write_text(json.dumps({'status':'PASS','scope':'fresh configured paired traces; deadline/result reconciliation and independent neural/federated replay; not a statistical policy evaluation','cases':reports},indent=2),encoding='utf-8')
    print('Result logic audit passed for all cases.')


if __name__=='__main__':main()
