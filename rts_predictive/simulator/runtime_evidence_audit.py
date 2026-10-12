"""Independent arithmetic and output checks on additive runtime evidence."""
import hashlib
import json
from rts_predictive.predictors.partial_output import validate_output,execute_output


def audit_runtime_evidence(events):
    certificates={};admissions={};outputs={};commits=0;checks=0;seed=None;required=False;bound_checks=set()
    for event in events:
        kind=event['event_type'];p=event['payload'];aid=event.get('attempt_id')
        if kind=='RUN_START':
            seed=p.get('seed');required=p.get('output_workload')=='SYNTHETIC_PREFIX_CLASSIFIER'
        elif kind=='FALLBACK_ANALYSIS':
            raw={k:v for k,v in p.items() if k!='certificate_sha256'}
            digest=hashlib.sha256(json.dumps(raw,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            if digest!=p['certificate_sha256']:raise ValueError('fallback certificate digest mismatch')
            rate=p['minimum_rate_ppm']
            bound=sum((x*1000000+rate-1)//rate for x in [p['own_work_us']]+[t['work_us'] for t in p['interference']]) if rate else None
            if bound!=p['response_bound_us']:raise ValueError('fallback response arithmetic mismatch')
            if p['status']=='VERIFIED' and (not rate or p['at_us']+bound+p['margin_us']>p['deadline_us'] or
                p['memory_required_mb']>p['memory_capacity_mb']):raise ValueError('infeasible fallback certificate')
            certificates[digest]=p
        elif kind=='FALLBACK_ADMITTED':
            cert=certificates.get(p['certificate_sha256'])
            if not cert or cert['status']!='VERIFIED' or cert['analyzed_task']!=event['task_id'] or cert['at_us']!=event['timestamp_us']:
                raise ValueError('fallback lacks matching admission certificate')
            admissions[aid]=cert
        elif kind=='OUTPUT_VALIDATION':
            outputs[aid]=p
            if p.get('valid') and not validate_output(p):raise ValueError('invalid claimed output')
            if p.get('valid') and seed is not None:
                expected=execute_output(seed,event['task_id'],p['head']=='prefix',p['checkpoint_id'])
                if any(p[k]!=expected[k] for k in ('input_sha256','output_sha256','probabilities','class_id')):
                    raise ValueError('output differs from actual workload replay')
        elif kind=='FALLBACK_BOUND_CHECK':
            cert=admissions.get(aid)
            if not cert or p['certificate_sha256']!=cert['certificate_sha256'] or not p['within_bound'] or \
               event['timestamp_us']-cert['at_us']>cert['response_bound_us']:
                raise ValueError('fallback completion exceeds bound')
            checks+=1
            bound_checks.add(aid)
        elif kind=='HOST_INFERENCE' and 'budget_us' in p:
            if p['overrun']!=(p['latency_us']>p['budget_us']):raise ValueError('incorrect inference budget status')
        elif kind=='TASK_COMMIT' and required:
            if aid not in outputs or not outputs[aid].get('valid') or not validate_output(outputs[aid]):
                raise ValueError('commit lacks valid executed output')
            if p['degraded'] and (aid not in admissions or aid not in bound_checks or outputs[aid]['head']!='prefix' or
                                 outputs[aid]['checkpoint_id']!=admissions[aid]['checkpoint_id']):
                raise ValueError('degraded commit lacks bound check or matching executed exit')
            if not p['degraded'] and outputs[aid]['head']!='full':raise ValueError('normal commit used an early head')
            commits+=1
    return {'status':'PASS','certificates':len(certificates),'admissions':len(admissions),
            'bounded_completions':checks,'validated_commits':commits}
