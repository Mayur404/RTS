"""User-facing explanations must respect identity, deadlines and unresolved work."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]
NODE=shutil.which('node')
SOURCE=(ROOT/'frontend/plain-results.js').read_text(encoding='utf-8')
pytestmark=pytest.mark.skipif(not NODE,reason='Node required')


def evaluate(x,expression='deriveResultSummary(x)'):
    out=subprocess.run([NODE,'-e',SOURCE+'\nconst x='+json.dumps(x)+';console.log(JSON.stringify('+expression+'));'],check=True,capture_output=True,text=True)
    return json.loads(out.stdout)


def snapshot(pairs,final=True):
    x={'devices':[{'device_id':'D','name':'Device'}],'time_us':1500,'release_end_us':1200,'end_us':1500,'comparison':{'final':final}}
    for i,side in enumerate(['before','after']):
        jobs=[{'id':str(n),'device':'D','workflow':'control','status':p[i],'release_us':0,'deadline_us':1000,**({'terminal_us':800+n} if p[i]!='ACTIVE' else {})} for n,p in enumerate(pairs)]
        met=sum(j['status']=='COMPLETE' for j in jobs);miss=sum(j['status']=='MISSED' for j in jobs)
        x[side]={'jobs':jobs,'tasks':[],'metrics':{'released_jobs':len(jobs),'completed_jobs':met,'missed_jobs':miss,'pending_jobs':len(jobs)-met-miss,'job_dmr_pct':miss/len(jobs)*100 if jobs else None}}
    return x


def test_rescued_minus_regressed_reconciles_final_miss_difference():
    x=snapshot([('COMPLETE','COMPLETE'),('MISSED','COMPLETE'),('MISSED','COMPLETE'),('COMPLETE','MISSED'),('MISSED','MISSED')])
    s=evaluate(x)
    assert s['paired']=={'both_met':1,'rescued':2,'regressed':1,'both_missed':1,'pending':0}
    assert s['net']==1 and not s['issues']
    message=evaluate(x,'resultExplanation(deriveResultSummary(x),x)')
    assert '1 deadline miss overall' in message['title']
    assert '2 workflows' in message['text'] and '1 workflow missed only' in message['text']


def test_unresolved_pairs_never_become_prevented_failures_or_final_benefit():
    x=snapshot([('MISSED','ACTIVE')],final=False)
    s=evaluate(x)
    assert s['paired']['rescued']==0 and s['paired']['pending']==1 and not s['issues']
    assert 'not final' in evaluate(x,'resultExplanation(deriveResultSummary(x),x)')['title']


def test_committed_fallback_task_does_not_imply_workflow_success():
    x=snapshot([('MISSED','MISSED')])
    x['after']['tasks']=[{'id':'t','job':'0','device':'D','state':'COMMITTED','commit_us':700,'deadline_us':750,'fallback_admitted':{'at_us':600}}]
    s=evaluate(x)
    assert s['recovery']['tasks']==1 and s['recovery']['finished']==1
    assert s['recovery']['workflows_finished']==0 and s['paired']['rescued']==0


def test_fallback_partition_preserves_missed_skipped_and_active_tasks():
    x=snapshot([('ACTIVE','ACTIVE')],final=False)
    x['after']['tasks']=[{'id':str(i),'job':'0','device':'D','state':state,'fallback_admitted':{'at_us':1},**({'commit_us':20,'deadline_us':30} if state=='COMMITTED' else {})} for i,state in enumerate(['COMMITTED','MISSED','SKIPPED','QUEUED'])]
    r=evaluate(x)['recovery']
    assert r['tasks']==r['finished']+r['missed']+r['skipped']+r['pending']==4
    assert (r['finished'],r['missed'],r['skipped'],r['pending'])==(1,1,1,1)


def test_workflow_timing_uses_completed_jobs_and_accepts_exact_deadline():
    x=snapshot([('COMPLETE','COMPLETE'),('MISSED','MISSED')])
    x['after']['jobs'][0]['terminal_us']=1000
    out=evaluate(x)
    assert out['timing']['after']=={'completed':1,'timed':1,'mean_us':1000,'max_us':1000,'min_slack_us':0}
    assert not out['issues']


def test_zero_misses_does_not_claim_positive_improvement():
    x=snapshot([('COMPLETE','COMPLETE')])
    message=evaluate(x,'resultExplanation(deriveResultSummary(x),x)')
    assert message['tone']=='neutral' and 'both runs' in message['title']


def test_regressions_produce_negative_explanation():
    x=snapshot([('COMPLETE','MISSED')])
    message=evaluate(x,'resultExplanation(deriveResultSummary(x),x)')
    assert message['tone']=='negative' and '1 extra deadline miss' in message['title']


def test_missing_workflow_identity_and_wrong_totals_are_flagged():
    x=snapshot([('COMPLETE','COMPLETE')]);x['after']['jobs'][0]['id']='wrong';x['after']['metrics']['completed_jobs']=99
    s=evaluate(x)
    assert len(s['issues'])>=2
    assert evaluate(x,'resultExplanation(deriveResultSummary(x),x)')['tone']=='review'


def test_late_committed_result_and_missing_timing_are_flagged():
    x=snapshot([('COMPLETE','COMPLETE')]);x['after']['jobs'][0].pop('terminal_us')
    x['after']['tasks']=[{'state':'COMMITTED','commit_us':20,'deadline_us':19}]
    assert len(evaluate(x)['issues'])==2


def test_no_releases_has_no_fabricated_average_or_prevention_count():
    x=snapshot([],final=False)
    s=evaluate(x)
    assert s['timing']['after']['mean_us'] is None and s['net']==0
    assert 'No workflows' in evaluate(x,'resultExplanation(deriveResultSummary(x),x)')['title']
