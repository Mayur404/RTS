"""Conditional finite-job RTA for the enforced highest-priority fallback lanes."""
import hashlib
import json
from rts_predictive.domain.runtime_evidence import FALLBACK_CERTIFICATE_SCHEMA_VERSION
from rts_predictive.domain.research import PPM, GPU_CPU_RESERVATION_PPM, CPU_TASK_MEMORY_MB, GPU_TASK_MEMORY_MB


def analyze_fallback(engine, task, point):
    host = task.origin
    gpu = task.gpu
    faults = [f for f in engine.config.faults if f.device_id == host
              and f.start_us < task.deadline and f.end_us > engine.now]
    background = max((f.gpu_ppm if gpu else f.cpu_ppm for f in faults), default=0)
    available = max(0, PPM-background-(0 if gpu else min(PPM-background, GPU_CPU_RESERVATION_PPM)))
    speed = engine.devices[host].gpu_speed_ppm if gpu else engine.devices[host].cpu_speed_ppm
    rate = speed*available//PPM*450000//PPM
    has_gpu = any(t.gpu for t in engine.tasks.values()) or any(
        any(d.resource.value == 'gpu' for d in s.resource_demands) for w in engine.config.workflows for s in w.tasks)
    memory_required = CPU_TASK_MEMORY_MB+(GPU_TASK_MEMORY_MB if has_gpu else 0)
    terms = []
    for a in engine.attempts.values():
        other = engine.tasks[a.task_uid]
        if a.host != host or other.gpu != gpu or a.task_uid == task.uid:
            continue
        if a.phase not in {'QUEUED','RUNNING','CANCEL_PENDING','CHECKPOINT'}:
            continue
        if a.fallback_order is not None or (gpu and engine.gpu[host] == a.lifecycle.attempt_id):
            work = a.remaining if a.degraded else max(0, other.spec.wcet_distribution.wcet_us-a.work_done)
            terms.append({'attempt_id':a.lifecycle.attempt_id,'work_us':work,
                          'kind':'admitted_fallback' if a.fallback_order is not None else 'nonpreemptive_blocking'})
    own = point.remaining_wcet_us+point.checkpoint_overhead_us
    response = sum((w*PPM+rate-1)//rate for w in [own]+[x['work_us'] for x in terms]) if rate else None
    supported = engine.policy in {'protected','reactive','predictive_no_fallback'}
    status = ('UNSUPPORTED' if not supported else 'NOT_SCHEDULABLE' if not rate or
              memory_required > engine.devices[host].memory_mb or
              engine.now+response+engine.config.margin_us > task.deadline else 'VERIFIED')
    certificate = {'certificate_schema_version':FALLBACK_CERTIFICATE_SCHEMA_VERSION,'analysis':'reserved-lane-finite-job-rta',
        'status':status,'configuration_hash':engine.config.config_hash,'analyzed_task':task.uid,
        'scheduler_contract':'fallback-priority-fifo/1.0','policy':engine.policy,
        'checkpoint_id':point.checkpoint_id,'at_us':engine.now,'deadline_us':task.deadline,
        'lane':'gpu' if gpu else 'cpu','minimum_rate_ppm':rate,'own_work_us':own,
        'interference':terms,'response_bound_us':response,'margin_us':engine.config.margin_us,
        'memory_required_mb':memory_required,'memory_capacity_mb':engine.devices[host].memory_mb,
        'assumptions':['fallback FIFO admission order above ordinary work and controller operations',
                       'declared work bounds hold; integer PPM service; thermal floor 450000',
                       'only configured faults; one CPU and one GPU slot; bounded lane memory',
                       'stage completion only; excludes successor and physical-system guarantees']}
    certificate['certificate_sha256'] = hashlib.sha256(json.dumps(certificate,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return certificate
