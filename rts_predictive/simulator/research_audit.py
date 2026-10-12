"""Independent lifecycle checks over canonical research traces, without the reducer."""
from collections import Counter
import hashlib
import math
import numpy as np
from rts_predictive.domain.research import TRACE_AUDIT_SCHEMA_VERSION, PPM, GPU_CPU_RESERVATION_PPM


class TraceAuditError(ValueError):
    pass


def audit_research_events(events, require_complete=True, *, devices=None):
    """Check optional canonical device specs against exposed sampled service rates.

    Older traces without rate fields remain auditable at their original scope.
    """
    hardware = {d['device_id']: d for d in devices} if devices is not None else None
    planned = {}; ready = {}; commits = {}; jobs = {}; attempts = {}; transfers = {}
    delivered = Counter(); returned = set(); count = 0; last_time = -1; last_sequence = 0
    done = False; run_id = None
    terminal_tasks = set(); lane_end = {}; radio_end = {}; predictions = {}
    failed_remote_transfers = {}; watchdog_checks = {}
    runtime_evidence=[]

    def need(condition, message, event):
        if not condition:
            raise TraceAuditError(f"sequence {event['sequence']}: {message}")

    for e in events:
        count += 1
        k, p, tid, aid = e['event_type'], e['payload'], e.get('task_id'), e.get('attempt_id')
        now = e['timestamp_us']
        if k in {'RUN_START','FALLBACK_ANALYSIS','FALLBACK_ADMITTED','FALLBACK_BOUND_CHECK','OUTPUT_VALIDATION','HOST_INFERENCE','TASK_COMMIT'}:
            runtime_evidence.append(e)
        need(type(now) is int and now >= last_time, 'non-monotonic integer clock', e)
        need(type(e['sequence']) is int and e['sequence'] > last_sequence, 'non-monotonic sequence', e)
        if run_id is None: run_id = e['run_id']
        need(e['run_id'] == run_id, 'mixed run identities', e)
        last_time, last_sequence = now, e['sequence']
        if k in {'SERVICE','CPU_OVERHEAD'}:
            need(type(p['work_us']) is int and p['work_us']>0, 'invalid delivered work or overhead', e)
            lane=(e['device_id'],p['lane'] if k=='SERVICE' else 'cpu')
            need(type(p['busy_us']) is int and p['busy_us']>0 and now>=p['busy_us'], 'invalid service interval', e)
            start=now-p['busy_us']
            need(start>=lane_end.get(lane,0), 'overlapping exclusive service intervals', e)
            lane_end[lane]=now
        if k == 'JOB_RELEASE':
            need(e['job_id'] not in jobs, 'duplicate job release', e)
            jobs[e['job_id']] = {**p, 'status': 'ACTIVE'}
        elif k == 'TASK_PLANNED':
            need(tid not in planned and e['job_id'] in jobs, 'duplicate or unowned planned task', e)
            planned[tid] = {**p, 'job': e['job_id'], 'origin': e['device_id']}
        elif k == 'TASK_READY':
            need(tid in planned and tid not in ready, 'unknown or repeatedly ready task', e)
            need(all(parent in commits for parent in planned[tid]['parents']), 'uncommitted predecessor', e)
            need(jobs[planned[tid]['job']]['status'] == 'ACTIVE', 'ready task in terminal job', e)
            ready[tid] = p['deadline_us']
        elif k in {'OFFLOAD_DISPATCH', 'ATTEMPT_CREATED'}:
            need(tid in ready and aid not in attempts, 'invalid attempt creation', e)
            need(tid not in terminal_tasks and jobs[planned[tid]['job']]['status']=='ACTIVE', 'attempt created for terminal task or job', e)
            attempts[aid] = {'task': tid, 'host': p['target'] if k == 'OFFLOAD_DISPATCH' else e['device_id'],
                             'remote': k == 'OFFLOAD_DISPATCH', 'complete': False, 'terminal': False}
        elif k == 'PREDICTION':
            need(tid in ready and tid not in terminal_tasks, 'prediction on unavailable task', e)
            need(type(p['miss_probability']) in (int,float) and math.isfinite(p['miss_probability']) and 0<=p['miss_probability']<=1, 'invalid neural probability', e)
            predictions[tid] = p
            if 'graph' in p:
                g=p['graph']; ids=g['node_ids']; features=g['features']; edges=g['edge_index']; query=g['query_index']
                need(g['feature_schema']=='research-task-resource/9-v3', 'unknown neural feature schema', e)
                need(isinstance(ids,list) and all(isinstance(i,str) for i in ids) and len(ids)==p['vertices'] and len(ids)>=5 and len(set(ids))==len(ids), 'invalid neural vertex identities', e)
                need(ids[:4]==['CPU','GPU','MEMORY','LINK'] and all(i in planned for i in ids[4:]), 'unknown neural graph vertex', e)
                need(g['node_kinds']==['resource']*4+['task']*(len(ids)-4), 'invalid neural node kinds', e)
                need(type(query) is int and 4<=query<len(ids) and ids[query]==tid, 'neural query belongs to another task', e)
                need(isinstance(features,list) and len(features)==len(ids) and all(isinstance(row,list) and len(row)==9 and all(type(v) in (int,float) and math.isfinite(v) and abs(v)<=np.finfo(np.float32).max for v in row) for row in features), 'invalid neural feature matrix', e)
                need(all(features[i][8]==int(i==query) for i in range(4,len(ids))), 'invalid neural queried-task flags', e)
                need(isinstance(edges,list) and len(edges)==2 and all(isinstance(row,list) and len(row)==p['edges'] and all(type(v) is int and 0<=v<len(ids) for v in row) for row in edges), 'invalid neural edge endpoints', e)
                digest=hashlib.sha256(np.asarray(features,dtype=np.float32).tobytes()+np.asarray(edges,dtype=np.int64).tobytes()).hexdigest()
                need(digest==p['graph_sha256'], 'neural tensor checksum mismatch', e)
        elif k == 'DECISION' and 'risk_gate' in p:
            need(all(type(p[key]) is bool for key in ('risk_gate','local_deadline_guard','feasibility_guard','high_risk')), 'invalid decision gate types', e)
            need(type(p['threshold']) in (int,float) and math.isfinite(p['threshold']) and 0<=p['threshold']<=1, 'invalid neural threshold', e)
            need(tid in predictions and p['prediction']==predictions[tid]['miss_probability'], 'decision disagrees with prediction', e)
            need(p['risk_gate']==(p['prediction']>=p['threshold']), 'neural threshold gate mismatch', e)
            need(type(p['deadline_margin_us']) is int and p['deadline_margin_us']>=0, 'invalid decision margin', e)
            need(p['local_deadline_guard']==(now+p['local_bound_us']+p['deadline_margin_us']>ready[tid]), 'local deadline guard mismatch', e)
            need(p['high_risk']==(p['risk_gate'] or p['local_deadline_guard'] or p['feasibility_guard']), 'combined decision gate mismatch', e)
        elif k == 'SERVICE':
            need(aid in attempts and not attempts[aid]['terminal'] and not attempts[aid]['complete'], 'service after cancellation or completion', e)
            need(attempts[aid]['task'] == tid, 'service belongs to another task', e)
            need(attempts[aid]['host'] == e['device_id'], 'service on wrong host', e)
            need(type(p['work_us']) is int and p['work_us'] > 0, 'invalid service amount', e)
            need(p['lane'] == ('gpu' if planned[tid]['gpu'] else 'cpu'), 'service on wrong resource', e)
            delivered[aid] += p['work_us']
        elif k == 'EXECUTION_COMPLETE':
            need(aid in attempts and not attempts[aid]['complete'] and not attempts[aid]['terminal'], 'duplicate or unknown execution completion', e)
            need(attempts[aid]['task'] == tid and attempts[aid]['host'] == e['device_id'], 'completion on wrong task or host', e)
            need(delivered[aid] == p['work_us'], 'execution service is not conserved', e)
            attempts[aid]['complete'] = True
        elif k in {'TASK_DEADLINE','TASK_SKIPPED'}:
            need(tid in planned and tid not in terminal_tasks and tid not in commits, 'task resolved twice', e)
            terminal_tasks.add(tid)
        elif k == 'TX_START':
            need(p['start_us'] >= now and p['end_us'] > p['start_us'], 'invalid transfer interval', e)
            need(p['transfer'] not in transfers, 'duplicate transfer identifier', e)
            if hardware is not None:
                source = e['device_id']
                need(source in hardware and p['target'] in hardware, 'unknown radio endpoint', e)
                need(type(p['bytes']) is int and p['bytes'] >= 0, 'invalid packet size', e)
                bandwidth = hardware[source]['bandwidth_mbps']
                serialization = max(1, (p['bytes']*8+bandwidth-1)//bandwidth)
                need(p['start_us'] >= radio_end.get(source, 0), 'overlapping sender radio serialization', e)
                radio_end[source] = p['start_us']+serialization
                need(p['end_us'] >= radio_end[source], 'packet arrives before serialization ends', e)
            if aid:
                need(aid in attempts and attempts[aid]['task'] == tid, 'transfer belongs to another attempt or task', e)
                origin, host = planned[tid]['origin'], attempts[aid]['host']
                source, target = (host, origin) if p['phase'] == 'result' else (origin, host)
                need(e['device_id'] == source and p['target'] == target, 'transfer on wrong route', e)
                if p['phase'] == 'result': need(attempts[aid]['complete'], 'result sent before execution completes', e)
            transfers[p['transfer']] = {'end': p['end_us'], 'attempt': aid, 'phase': p['phase'],
                                       'source': e['device_id'], 'target': p['target']}
        elif k in {'TX_END', 'PACKET_LOSS'}:
            tx = transfers.pop(p['transfer'], None)
            need(tx is not None and tx['end'] == now, 'arrival without matching transfer interval', e)
            need(tx['attempt'] == aid and tx['phase'] == p['phase'], 'arrival changed attempt or phase', e)
            need(e['device_id'] == tx['target' if k == 'TX_END' else 'source'], 'arrival on wrong host', e)
            if k == 'TX_END' and p['phase'] == 'result': returned.add(aid)
        elif k == 'TRANSFER_FAILED' and p['phase'] in {'request','result'}:
            need(aid in attempts and attempts[aid]['task']==tid, 'failed transfer on unknown attempt', e)
            failed_remote_transfers[aid]=p['phase']
        elif k == 'WATCHDOG_CHECK' and 'next_check_us' in p:
            need(aid in attempts and attempts[aid]['task']==tid and attempts[aid]['remote'], 'watchdog on wrong attempt', e)
            failed=failed_remote_transfers.get(aid)
            need(p['remote_transfer_failed']==failed, 'watchdog delivery failure differs from trace', e)
            remote=p['remote_bound_us'];recovery=p['recovery_bound_us'];margin=p['margin_us']
            need(type(margin) is int and margin>=0 and type(p['next_check_us']) is int and p['next_check_us']>now, 'invalid watchdog window', e)
            need((remote is None and failed is not None) or (failed is None and type(remote) is int and remote>=0), 'invalid watchdog remote bound', e)
            if recovery is None:
                need(p['latest_abort_us'] is None, 'missing recovery has an abort window', e)
                expected_abort=False;expected_reason='no_admissible_fallback'
            else:
                need(type(recovery) is int and recovery>0 and p['latest_abort_us']==ready[tid]-recovery-margin, 'incorrect latest abort time', e)
                late=remote is not None and now+remote+margin>ready[tid]
                closing=p['next_check_us']>=p['latest_abort_us']
                expected_abort=bool(failed or late or closing)
                expected_reason='remote_transfer_failed' if failed else 'remote_bound_exceeds_deadline' if late else 'fallback_window_closing' if closing else 'remote_within_window'
            need(p['action']==('ABORT' if expected_abort else 'CONTINUE') and p['reason']==expected_reason, 'watchdog action or reason differs from recorded gates', e)
            watchdog_checks[aid]=e
        elif k == 'WATCHDOG_ABORT' and aid in watchdog_checks:
            check=watchdog_checks[aid]
            need(check['timestamp_us']==now and check['payload']['action']=='ABORT', 'abort lacks matching watchdog observation', e)
        elif k in {'CANCEL_ACK', 'ATTEMPT_LEASE_EXPIRED'}:
            need(aid in attempts and delivered[aid] == p['wasted_work_us'], 'cancelled service is not conserved', e)
            need(attempts[aid]['task'] == tid and attempts[aid]['host'] == e['device_id'], 'cancellation on wrong task or host', e)
            attempts[aid]['terminal'] = True
        elif k == 'TASK_COMMIT':
            need(tid in ready and tid not in commits, 'duplicate or unready commitment', e)
            need(tid not in terminal_tasks and jobs[planned[tid]['job']]['status']=='ACTIVE', 'commitment in terminal task or job', e)
            need(now <= ready[tid], 'commit after deadline', e)
            need(aid in attempts and attempts[aid]['task'] == tid and attempts[aid]['complete'], 'commit without completed execution', e)
            need(not attempts[aid]['remote'] or aid in returned, 'remote commitment before result delivery', e)
            commits[tid] = aid; attempts[aid]['terminal'] = True
        elif k in {'JOB_COMPLETE', 'JOB_MISS'}:
            job = jobs[e['job_id']]
            need(job['status'] == 'ACTIVE', 'job resolved twice', e)
            if k == 'JOB_COMPLETE':
                need(now <= job['deadline_us'], 'job completed after deadline', e)
                need(all(f"{e['job_id']}/{name}" in commits for name in job['stages']), 'job completed without all stage results', e)
            job['status'] = 'COMPLETE' if k == 'JOB_COMPLETE' else 'MISSED'
        elif k == 'RESOURCE_SAMPLE':
            need(0 <= p['memory_mb'] <= p['memory_capacity_mb'], 'memory exceeds capacity', e)
            need(p['cpu_slot'] is None or p['cpu_slot'] != p['gpu_slot'], 'attempt owns two execution lanes', e)
            if hardware is not None:
                need(e['device_id'] in hardware, 'sample on unknown configured device', e)
                spec = hardware[e['device_id']]
                need(p['memory_capacity_mb'] == spec['memory_mb'], 'sample changed configured memory capacity', e)
                if 'cpu_rate_ppm' in p or 'gpu_rate_ppm' in p:
                    for field in ('background_cpu_ppm', 'background_gpu_ppm', 'thermal_ppm'):
                        need(type(p[field]) is int and 0 <= p[field] <= PPM, 'invalid sampled capacity fraction', e)
                    reserve = min(PPM-p['background_cpu_ppm'], GPU_CPU_RESERVATION_PPM if p['gpu_slot'] else 0)
                    thermal = max(450000, PPM-max(0, p['temperature_millic']-70000)*15)
                    need(p['thermal_ppm'] == thermal, 'thermal rate differs from sampled temperature', e)
                    cpu_rate = spec['cpu_speed_ppm']*(PPM-p['background_cpu_ppm']-reserve)//PPM*p['thermal_ppm']//PPM
                    gpu_rate = spec['gpu_speed_ppm']*(PPM-p['background_gpu_ppm'])//PPM*p['thermal_ppm']//PPM
                    need(p.get('gpu_cpu_reservation_ppm') == reserve, 'GPU CPU reservation differs from capacity model', e)
                    need(p['cpu_ppm'] == (PPM if p['cpu_slot'] else p['background_cpu_ppm']+reserve)
                         and p['gpu_ppm'] == (PPM if p['gpu_slot'] else p['background_gpu_ppm']),
                         'sampled occupancy differs from slot ownership and interference', e)
                    need(p.get('cpu_rate_ppm') == cpu_rate and p.get('gpu_rate_ppm') == gpu_rate,
                         'sampled service rate differs from configured hardware and capacity', e)
            for a in p['attempts']:
                need(a['attempt'] in attempts and attempts[a['attempt']]['task'] == a['task'], 'unknown sampled attempt', e)
                need(a['host'] == e['device_id'], 'attempt in wrong resource sample', e)
                need(a['work_done_us'] + a['remaining_us'] == a['total_work_us'], 'remaining work is not conserved', e)
                need(delivered[a['attempt']] == a['work_done_us'], 'resource progress differs from service trace', e)
                if a['phase'] == 'RUNNING':
                    slot = p['gpu_slot'] if planned[a['task']]['gpu'] else p['cpu_slot']
                    need(slot == a['attempt'], 'running attempt does not own its slot', e)
        elif k == 'RUN_COMPLETE':
            need(not done, 'run completed twice', e)
            need(all(j['status'] != 'ACTIVE' for j in jobs.values()), 'drain left unresolved jobs', e)
            done = True
    if require_complete and not done: raise TraceAuditError('trace is incomplete')
    from rts_predictive.simulator.runtime_evidence_audit import audit_runtime_evidence
    try:runtime_audit=audit_runtime_evidence(runtime_evidence)
    except ValueError as exc:raise TraceAuditError(str(exc)) from exc
    return {'schema_version': TRACE_AUDIT_SCHEMA_VERSION, 'run_id': run_id, 'status': 'PASS',
            'runtime_evidence':runtime_audit,
            'canonical_events': count, 'jobs': len(jobs), 'attempts': len(attempts),
            'committed_tasks': len(commits), 'remote_commits': sum(attempts[a]['remote'] for a in commits.values()),
            'delivered_service_us': sum(delivered.values()), 'complete': done,
            'scope': 'simulator trace consistency; not a timing or physical safety certificate'}
