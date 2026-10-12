"""Layered integer-time simulation; physical hardware is explicitly abstracted."""
from __future__ import annotations
import heapq
import math
import random
import time
from copy import deepcopy
from dataclasses import asdict
from rts_predictive.domain.research import (PPM, GPU_CPU_RESERVATION_PPM, CPU_TASK_MEMORY_MB, GPU_TASK_MEMORY_MB, ResearchConfig, ResearchTask, ResearchJob,
                                          ResearchAttemptWork, ResearchOperation)
from rts_predictive.domain.lifecycle import ExecutionAttempt, AttemptKind, AttemptState
from rts_predictive.simulator.rng import derive_stream_seed
from rts_predictive.artifacts.events import EVENT_SCHEMA_VERSION


def ceil_div(a,b):
    return (a+b-1)//b


class ResearchEngine:
    """One policy on a fixed, shared exogenous scenario.

    Float values exist only at neural/model-display boundaries. The event clock,
    execution work, residuals, thermal state and resource rates are integers.
    """
    def __init__(self, config: ResearchConfig, policy="protected", models=None, run_id="research",
                 enable_watchdog=True, enable_fl=True, enable_offload=True, enable_fallback=True):
        if policy not in {"protected","edf","fifo","rm","always_offload","reactive","predictive_no_fallback"}:
            raise ValueError("unsupported research policy")
        if any(type(value) is not bool for value in (enable_watchdog,enable_fl,enable_offload,enable_fallback)):
            raise ValueError("research feature flags must be booleans")
        self.neural=policy in {"protected","predictive_no_fallback"}
        if self.neural and models is None:
            from rts_predictive.predictors.research_adapter import ResearchModels
            models=ResearchModels()
        self.config,self.policy,self.models,self.run_id=config,policy,models,run_id
        self.enable_watchdog=enable_watchdog and self.neural
        self.enable_fl=enable_fl and self.neural
        self.enable_offload=enable_offload
        self.enable_fallback=enable_fallback and policy!="predictive_no_fallback"
        self.now=0; self.sequence=0; self.queue=[]; self.events=[]; self._insert=0
        self.devices={d.device_id:d for d in config.devices}
        self.fl_coordinator=min(self.devices,key=lambda host:(-self.devices[host].cpu_speed_ppm,host))
        self.jobs={}; self.tasks={}; self.attempts={}; self.operations={}
        self.cpu={d:None for d in self.devices}; self.gpu={d:None for d in self.devices}
        self.temperature={d:35000 for d in self.devices}; self.radio={d:0 for d in self.devices}
        self.transfers={}; self._attempt_sequence=0; self._operation_sequence=0; self._tx_sequence=0
        self._failed_remote_transfers={}
        self.fl_round=None; self.fl_rounds=0; self.done=False
        self.estimator_published_us=0
        self._fallback_sequence=0
        self._fallback_candidates={}
        self._listeners=[]
        self.emit("RUN_START",config_sha256=config.config_hash,policy=policy,
                  seed=config.seed,output_workload='SYNTHETIC_PREFIX_CLASSIFIER',
                  release_end_us=config.release_end_us,end_us=config.end_us,fl_coordinator=self.fl_coordinator)
        for device in config.devices:
            for wi,workflow in enumerate(config.workflows):
                offset=wi*2500
                k=0
                while offset+k*workflow.period_us<config.release_end_us:
                    self.push(offset+k*workflow.period_us,"RELEASE",(device.device_id,workflow,k))
                    k+=1
        for fault in config.faults:
            self.push(fault.start_us,"FAULT",fault)
            self.push(fault.end_us,"FAULT_END",fault)
        self.push(5000,"SAMPLE")
        if self.enable_fl:
            self.push(config.fl_period_us,"FL_ROUND")

    def subscribe(self,listener):
        self._listeners.append(listener)

    def push(self,at,kind,payload=None):
        if type(at) is not int or at<self.now:
            raise ValueError("events require monotonic integer microseconds")
        self._insert+=1
        priority={"BOUNDARY":0,"OP_DONE":0,"DELIVER":1,"RELEASE":2,"DEADLINE":4,"JOB_DEADLINE":5}.get(kind,3)
        heapq.heappush(self.queue,(at,priority,self._insert,kind,payload))

    def emit(self,kind,task=None,attempt=None,device=None,job=None,**payload):
        self.sequence+=1
        event={"schema_version":EVENT_SCHEMA_VERSION,"run_id":self.run_id,"sequence":self.sequence,
               "timestamp_us":self.now,"event_type":kind,"device_id":device or (task.origin if task else None),
               "job_id":job or (task.job_id if task else None),"task_id":task.uid if task else None,
               "attempt_id":attempt.lifecycle.attempt_id if attempt else None,"payload":payload}
        self.events.append(event)
        for listener in self._listeners: listener(event)
        return event

    def _faults(self,host):
        return [f for f in self.config.faults if f.device_id==host and f.start_us<=self.now<f.end_us]

    def resource(self,host):
        faults=self._faults(host)
        bg_cpu=max((f.cpu_ppm for f in faults),default=0)
        bg_gpu=max((f.gpu_ppm for f in faults),default=0)
        reserve=GPU_CPU_RESERVATION_PPM if self.gpu[host] else 0
        cpu=bg_cpu+min(PPM-bg_cpu,reserve)
        if self.cpu[host]: cpu=PPM
        gpu=PPM if self.gpu[host] else bg_gpu
        mem=sum(self._memory(self.tasks[a.task_uid]) for a in self.attempts.values()
                if a.host==host and a.phase in {"RUNNING","CANCEL_PENDING"})
        thermal=max(450000,PPM-max(0,self.temperature[host]-70000)*15)
        effective_reserve=min(PPM-bg_cpu,reserve)
        cpu_rate=self.devices[host].cpu_speed_ppm*max(0,PPM-bg_cpu-effective_reserve)//PPM*thermal//PPM
        gpu_rate=self.devices[host].gpu_speed_ppm*(PPM-bg_gpu)//PPM*thermal//PPM
        return {"cpu_ppm":cpu,"gpu_ppm":gpu,"background_cpu_ppm":bg_cpu,"background_gpu_ppm":bg_gpu,
                "cpu_rate_ppm":cpu_rate,"gpu_rate_ppm":gpu_rate,"gpu_cpu_reservation_ppm":effective_reserve,
                "thermal_ppm":thermal,"temperature_millic":self.temperature[host],
                "memory_mb":mem,"memory_capacity_mb":self.devices[host].memory_mb,
                "bandwidth_mbps":self.devices[host].bandwidth_mbps,
                "link_extra_us":max((f.extra_link_us for f in faults),default=0),
                "loss_ppm":max(self.config.loss_ppm,max((f.loss_ppm for f in faults),default=0))}

    def rate(self,host,gpu=False):
        state=self.resource(host)
        return state["gpu_rate_ppm" if gpu else "cpu_rate_ppm"]

    def _work_bound(self,host,work,gpu=False):
        rate=self.rate(host,gpu)
        return ceil_div(max(0,work)*PPM,rate) if rate else self.config.end_us+1

    def _memory(self,task):
        return GPU_TASK_MEMORY_MB if task.gpu else CPU_TASK_MEMORY_MB

    def _advance(self,at):
        dt=at-self.now
        service_events=[]
        for host in self.devices:
            for lane,slot in (("cpu",self.cpu[host]),("gpu",self.gpu[host])):
                if slot is None: continue
                work=self.operations.get(slot) or self.attempts.get(slot)
                if work is None: continue
                delivered,work.residual=divmod(dt*self.rate(host,lane=="gpu")+work.residual,PPM)
                if isinstance(work,ResearchOperation):
                    consumed=min(work.remaining,delivered);work.remaining-=consumed
                    if consumed: service_events.append(("CPU_OVERHEAD",{"device":host,"category":work.kind,"work_us":consumed,"busy_us":dt}))
                else:
                    consumed=min(work.remaining,max(0,work.layer_end-work.work_done),delivered)
                    work.remaining-=consumed;work.work_done+=consumed;work.compute_time_us+=dt
                    work.lifecycle.charge(service_us=consumed)
                    task=self.tasks[work.task_uid]
                    if task.current_attempt==slot: task.delivered_work=work.work_done
                    if consumed: service_events.append(("SERVICE",{"task":task,"attempt":work,"device":host,
                                                                    "work_us":consumed,"busy_us":dt,"lane":lane}))
        self.now=at
        for kind,payload in service_events:self.emit(kind,**payload)

    def run_until(self,at):
        if type(at) is not int or at<self.now: raise ValueError("integer monotonic horizon required")
        at=min(at,self.config.end_us)
        if self.done: return
        while self.queue and self.queue[0][0]<=at:
            stamp,_,_,kind,payload=heapq.heappop(self.queue)
            self._advance(stamp)
            self._handle(kind,payload)
            self._schedule()
        self._advance(at)
        if at==self.config.end_us:
            self.done=True
            if self.fl_round: self.emit("FL_ROUND_INCOMPLETE",round=self.fl_round["id"])
            self.emit("RUN_COMPLETE")
        self.sample()

    def _handle(self,kind,p):
        if kind=="RELEASE": self._release(*p)
        elif kind=="DEADLINE":
            t=self.tasks[p]
            if t.status not in {"COMMITTED","MISSED","SKIPPED"}: self._miss(t,"stage_deadline")
        elif kind=="JOB_DEADLINE":
            j=self.jobs[p]
            if j.status=="ACTIVE": self._drop(j,"end_to_end_deadline")
        elif kind=="BOUNDARY":
            aid,generation=p; a=self.attempts[aid]
            if a.generation==generation and a.phase in {"RUNNING","CANCEL_PENDING"} and a.work_done>=a.layer_end:
                self._boundary(a)
        elif kind=="OP_DONE":
            uid,generation=p;op=self.operations.get(uid)
            if op and op.generation==generation and op.remaining==0:
                if self.cpu[op.host]==uid:self.cpu[op.host]=None
                del self.operations[uid];self._operation_done(op)
        elif kind=="DELIVER": self._deliver(p)
        elif kind in {"FAULT","FAULT_END"}:
            details=asdict(p);details.pop("device_id")
            self.emit("FAULT_START" if kind=="FAULT" else "FAULT_END",device=p.device_id,**details)
        elif kind=="LEASE":
            a=self.attempts[p]
            if a.lifecycle.state not in {AttemptState.COMPLETED,AttemptState.COMMITTED,AttemptState.CANCELLED,AttemptState.LATE_RESULT_DISCARDED}:
                self._ack(a,lease=True)
        elif kind=="SAMPLE":
            for host in self.devices:
                r=self.resource(host)
                target=35000+(r["cpu_ppm"]*22000+r["gpu_ppm"]*30000)//PPM
                self.temperature[host]+=(target-self.temperature[host])*5000//400000
            self.sample()
            if self.now+5000<=self.config.end_us:self.push(self.now+5000,"SAMPLE")
        elif kind=="WATCHDOG":
            t=self.tasks[p]
            if t.status not in {"COMMITTED","MISSED","SKIPPED"}:
                self._op(t.origin,"watchdog",20,t.deadline,{"task":p})
        elif kind=="FL_ROUND": self._start_fl()

    def _release(self,host,workflow,k):
        uid=f"{host}/{workflow.pipeline_id}/{k}"
        j=ResearchJob(uid,host,workflow,self.now,self.now+workflow.end_to_end_deadline_us)
        self.jobs[uid]=j
        self.emit("JOB_RELEASE",device=host,job=uid,workflow=workflow.pipeline_id,deadline_us=j.deadline,
                  stages=[t.task_id for t in workflow.tasks],edges=list(workflow.dependency_edges))
        for spec in workflow.tasks:
            tid=f"{uid}/{spec.task_id}"
            parents=tuple(f"{uid}/{source}" for source,target in workflow.dependency_edges if target==spec.task_id)
            rng=random.Random(derive_stream_seed(self.config.seed,f"research/work/{tid}"))
            demand=(spec.wcet_distribution.nominal_us if spec.wcet_distribution.kind=="constant" else
                    rng.randint(spec.wcet_distribution.bcet_us,spec.wcet_distribution.wcet_us))
            task=ResearchTask(tid,uid,host,spec,parents,demand=demand,deadline=j.deadline)
            j.tasks[spec.task_id]=task;self.tasks[tid]=task
            self.emit("TASK_PLANNED",task=task,name=spec.task_id,parents=list(parents),
                      nominal_work_us=spec.wcet_distribution.wcet_us,gpu=task.gpu,
                      critical=task.critical,layers=self.config.layer_count if task.gpu else 1,memory_demand_mb=self._memory(task))
        for task in j.tasks.values():
            if not task.parents:self._ready(task)
        self.push(j.deadline,"JOB_DEADLINE",uid)

    def _ready(self,t):
        if self.jobs[t.job_id].status!="ACTIVE" or t.status!="BLOCKED":return
        if any(self.tasks[p].status!="COMMITTED" for p in t.parents):raise AssertionError("precedence violation")
        t.ready_us=self.now;t.deadline=min(self.now+t.spec.relative_deadline_us,self.jobs[t.job_id].deadline)
        t.status="DECIDING"
        self.emit("TASK_READY",task=t,name=t.spec.task_id,deadline_us=t.deadline,critical=t.critical)
        needs=(self.neural or self.policy in {"reactive","always_offload"}) and (t.spec.offloadable or t.spec.exit_points)
        cost=self.config.dispatch_cost_us+(self.config.inference_cost_us if needs and self.neural else 0)
        self._op(t.origin,"decision" if needs else "dispatch",cost,t.deadline,{"task":t.uid})
        self.push(t.deadline,"DEADLINE",t.uid)

    def _op(self,host,kind,work,deadline,payload):
        self._operation_sequence+=1; uid=f"op-{self._operation_sequence}"
        self.operations[uid]=ResearchOperation(uid,host,kind,work,deadline,payload)
        return uid

    def _operation_done(self,op):
        if op.kind in {"decision","dispatch"}:
            t=self.tasks[op.payload["task"]]
            if t.status in {"MISSED","SKIPPED","COMMITTED"}:return
            if op.kind=="decision":self._decide(t,op.payload.get("attempt"))
            else:self._new_attempt(t,t.origin)
        elif op.kind=="watchdog":self._watchdog(self.tasks[op.payload["task"]])
        elif op.kind=="fl_train":self._fl_trained(op)
        elif op.kind=="fl_aggregate":self._fl_aggregate()

    def _new_attempt(self,t,host,degraded=False,exit_point=None):
        self._attempt_sequence+=1;uid=f"{t.uid}@{self._attempt_sequence}"
        kind=AttemptKind.DEGRADED if degraded else (AttemptKind.LOCAL if host==t.origin else AttemptKind.REMOTE)
        lifecycle=ExecutionAttempt(uid,t.uid,kind,host,created_at_us=self.now);lifecycle.dispatch()
        total=(exit_point.remaining_wcet_us+exit_point.checkpoint_overhead_us) if degraded else t.demand
        a=ResearchAttemptWork(lifecycle,t.uid,host,total,total,degraded,
                              exit_point.output_utility if degraded else t.spec.output_utility)
        a.layer_end=total if degraded or not t.gpu else ceil_div(total,self.config.layer_count)
        self.attempts[uid]=a;t.current_attempt=uid;t.degraded=degraded;t.delivered_work=0
        if degraded:self._admit_fallback(t,a,exit_point)
        if host!=t.origin:
            a.queued=False;a.phase="REQUEST_TX";t.status="OFFLOADED"
            self.emit("OFFLOAD_DISPATCH",task=t,attempt=a,device=t.origin,target=host,
                      model_version=self.models.version if self.models else 0)
            self._send(t.origin,host,t.spec.request_payload_bytes,"request",a)
            self.push(t.deadline,"LEASE",uid)
            if self.enable_watchdog:self.push(self.now+self.config.watchdog_period_us,"WATCHDOG",t.uid)
        else:
            t.status="QUEUED"
            self.emit("ATTEMPT_CREATED",task=t,attempt=a,device=host,total_work_us=total,degraded=degraded,
                      utility=a.utility)
        return a

    def _key(self,a):
        t=self.tasks[a.task_uid]
        if self.policy=="fifo":return (t.ready_us,0,t.uid,a.lifecycle.attempt_id)
        if self.policy=="rm":return (self.jobs[t.job_id].workflow.period_us,-t.spec.priority,t.uid,a.lifecycle.attempt_id)
        return (t.deadline,0 if t.critical else 1,t.uid,a.lifecycle.attempt_id)

    def _schedule(self):
        for host in self.devices:
            # A running GPU remains non-preemptive until its next layer boundary.
            if self.gpu[host] is None:
                options=[a for a in self.attempts.values() if a.host==host and a.queued
                         and self.tasks[a.task_uid].gpu and a.phase=="QUEUED"]
                for a in sorted(options,key=lambda a:(0,a.fallback_order) if a.fallback_order is not None else (1,self._key(a))):
                    if self.resource(host)["memory_mb"]+self._memory(self.tasks[a.task_uid])<=self.devices[host].memory_mb:
                        self._start(a,True);break
            ops=[op for op in self.operations.values() if op.host==host]
            options=[a for a in self.attempts.values() if a.host==host and not self.tasks[a.task_uid].gpu
                     and a.phase in {"QUEUED","RUNNING","CANCEL_PENDING"}]
            choices=[((op.kind.startswith("fl_"),op.deadline,0,op.uid),op.uid) for op in ops]
            if self.policy in {"fifo","rm"}:
                choices=[]
                for op in ops:
                    task=self.tasks.get(op.payload.get("task"))
                    rank=(task.ready_us if self.policy=="fifo" else self.jobs[task.job_id].workflow.period_us) if task else op.deadline
                    choices.append(((op.kind.startswith("fl_"),rank,0,op.uid),op.uid))
            for a in options:
                old_cpu=self.attempts.get(self.cpu[host])
                replaced_memory=self._memory(self.tasks[old_cpu.task_uid]) if old_cpu and old_cpu.phase in {"RUNNING","CANCEL_PENDING"} else 0
                if a.phase!="QUEUED" or self.resource(host)["memory_mb"]-replaced_memory+self._memory(self.tasks[a.task_uid])<=self.devices[host].memory_mb:
                    task=self.tasks[a.task_uid]
                    rank=task.ready_us if self.policy=="fifo" else self.jobs[task.job_id].workflow.period_us if self.policy=="rm" else task.deadline
                    choices.append((((-1,a.fallback_order,1,a.lifecycle.attempt_id) if a.fallback_order is not None
                                     else (False,rank,1,a.lifecycle.attempt_id)),a.lifecycle.attempt_id))
            chosen=min(choices)[1] if choices else None
            old=self.cpu[host]
            if self.policy=="fifo" and old in self.attempts and self.attempts[old].phase=="RUNNING":chosen=old
            if old!=chosen:
                if old in self.attempts:
                    a=self.attempts[old]
                    a.phase="QUEUED";a.queued=True;a.generation+=1
                    self.emit("PREEMPT",task=self.tasks[a.task_uid],attempt=a,device=host)
                elif old in self.operations:self.operations[old].generation+=1
                self.cpu[host]=chosen
                if chosen in self.attempts:self._start(self.attempts[chosen],False)
            for gpu,uid in ((False,self.cpu[host]),(True,self.gpu[host])):
                if uid is None:continue
                work=self.operations.get(uid) or self.attempts[uid]
                remain=work.remaining if isinstance(work,ResearchOperation) else work.layer_end-work.work_done
                rate=self.rate(host,gpu)
                if remain==0:at=self.now
                elif rate==0:continue
                else:at=self.now+max(0,ceil_div(max(0,remain*PPM-work.residual),rate))
                signature=(at,work.generation)
                if getattr(work,"scheduled_signature",None)!=signature:
                    work.scheduled_signature=signature
                    self.push(at,"OP_DONE" if isinstance(work,ResearchOperation) else "BOUNDARY",(uid,work.generation))

    def _start(self,a,gpu):
        aid=a.lifecycle.attempt_id; t=self.tasks[a.task_uid]
        if a.lifecycle.state in {AttemptState.CREATED,AttemptState.DISPATCHED}:a.lifecycle.start(self.now)
        a.phase="CANCEL_PENDING" if a.lifecycle.state is AttemptState.CANCEL_REQUESTED else "RUNNING"
        a.queued=False
        a.generation+=1
        if gpu:self.gpu[a.host]=aid
        else:self.cpu[a.host]=aid
        if not a.observed_resource:a.observed_resource=self.resource(a.host)
        if t.current_attempt==aid and t.status not in {"COMMITTED","MISSED","SKIPPED"}:t.status="RUNNING"
        self.emit("EXECUTION_START",task=t,attempt=a,device=a.host,remote=a.host!=t.origin,
                  layer=a.layer+1,degraded=a.degraded,total_work_us=a.total,current_attempt=t.current_attempt==aid)

    def _remove(self,a):
        aid=a.lifecycle.attempt_id;a.generation+=1;a.queued=False
        if self.cpu[a.host]==aid:self.cpu[a.host]=None
        if self.gpu[a.host]==aid:self.gpu[a.host]=None

    def _boundary(self,a):
        t=self.tasks[a.task_uid];self._remove(a)
        if a.remaining<=0:
            a.phase="COMPLETED";valid=a.lifecycle.complete(self.now)
            if valid:
                from rts_predictive.predictors.partial_output import execute_output,validate_output
                a.output_record=execute_output(self.config.seed,t.uid,a.degraded,a.exit_checkpoint)
                self.emit("OUTPUT_VALIDATION",task=t,attempt=a,device=a.host,
                          **(a.output_record if validate_output(a.output_record) else {'valid':False,'reason':'invalid_tensor_or_contract'}))
            self.emit("EXECUTION_COMPLETE",task=t,attempt=a,device=a.host,work_us=a.work_done,
                      compute_time_us=a.compute_time_us,degraded=a.degraded)
            if self.models and not a.degraded and valid:
                self.models.observe(t,self.devices[a.host],a.observed_resource,a.compute_time_us,self.now<=t.deadline)
                self.emit("PRIVATE_OBSERVATION",task=t,attempt=a,device=a.host,
                          features=self.models.features(t,self.devices[a.host],a.observed_resource).tolist()[0],
                          service_time_us=a.compute_time_us,execution_on_time=self.now<=t.deadline,
                          scope="execution_service_not_end_to_end_delivery")
            if a.host!=t.origin:
                a.phase="RESULT_TX";self._send(a.host,t.origin,t.spec.result_payload_bytes,"result",a)
            elif valid:self._commit(t,a)
            else:self.emit("LATE_RESULT_DISCARDED",task=t,attempt=a)
        else:
            a.layer+=1
            self.emit("CHECKPOINT",task=t,attempt=a,device=a.host,layer=a.layer,work_done_us=a.work_done)
            if a.lifecycle.state is AttemptState.CANCEL_REQUESTED:
                a.phase="QUEUED";a.queued=True
            elif (self.neural or self.policy=="reactive") and a.host==t.origin and not a.degraded:
                a.phase="CHECKPOINT";t.status="DECIDING"
                cost=self.config.inference_cost_us if self.neural else self.config.dispatch_cost_us
                self._op(t.origin,"decision",cost,t.deadline,{"task":t.uid,"attempt":a.lifecycle.attempt_id})
            else:a.phase="QUEUED";a.queued=True
            a.layer_end=min(a.total,ceil_div(a.total*(a.layer+1),self.config.layer_count))

    def _commit(self,t,a):
        if t.committed_attempt or t.status in {"MISSED","SKIPPED"} or self.jobs[t.job_id].status!="ACTIVE" or self.now>t.deadline or t.current_attempt!=a.lifecycle.attempt_id:
            self.emit("LATE_RESULT_DISCARDED",task=t,attempt=a);return
        if a.lifecycle.state is not AttemptState.COMPLETED:
            self.emit("LATE_RESULT_DISCARDED",task=t,attempt=a);return
        # Execute the workload head, rather than accepting a scalar utility as output.
        from rts_predictive.predictors.partial_output import execute_output,validate_output
        if a.output_record is None:
            a.output_record=execute_output(self.config.seed,t.uid,a.degraded,a.exit_checkpoint)
            self.emit("OUTPUT_VALIDATION",task=t,attempt=a,
                      **(a.output_record if validate_output(a.output_record) else {'valid':False,'reason':'invalid_tensor_or_contract'}))
        if not a.output_record.get('valid') or not validate_output(a.output_record):
            self.emit("OUTPUT_REJECTED",task=t,attempt=a,reason="invalid_executed_output")
            self._miss(t,"invalid_executed_output");return
        if a.fallback_certificate:
            certificate=a.fallback_certificate
            within=self.now<=certificate['at_us']+certificate['response_bound_us']
            self.emit("FALLBACK_BOUND_CHECK",task=t,attempt=a,within_bound=within,
                      certificate_sha256=certificate['certificate_sha256'],
                      response_us=self.now-certificate['at_us'],response_bound_us=certificate['response_bound_us'])
            if not within:raise AssertionError("enforced fallback exceeded its conditional response bound")
        a.lifecycle.state=AttemptState.COMMITTED;a.phase="COMMITTED"
        t.committed_attempt=a.lifecycle.attempt_id;t.status="COMMITTED"
        self.emit("TASK_COMMIT",task=t,attempt=a,name=t.spec.task_id,response_time_us=self.now-t.ready_us,
                  critical=t.critical,utility=a.utility,degraded=a.degraded)
        j=self.jobs[t.job_id]
        for successor in j.tasks.values():
            if successor.status=="BLOCKED" and all(self.tasks[p].status=="COMMITTED" for p in successor.parents):self._ready(successor)
        if t.spec.task_id==j.workflow.sink_task_id:
            j.status="COMPLETE"
            self.emit("JOB_COMPLETE",device=j.origin,job=j.uid,workflow=j.workflow.pipeline_id,
                      response_time_us=self.now-j.release,deadline_us=j.deadline)

    def _cancel(self,a,reason):
        t=self.tasks[a.task_uid]
        if a.lifecycle.state in {AttemptState.COMMITTED,AttemptState.CANCELLED,AttemptState.LATE_RESULT_DISCARDED,AttemptState.FAILED}:return
        if a.lifecycle.state is AttemptState.COMPLETED:
            a.lifecycle.discard_late_result(self.now);return
        a.lifecycle.request_cancel()
        self.emit("CANCEL_REQUEST",task=t,attempt=a,device=t.origin,target=a.host,reason=reason)
        if a.host==t.origin:self._ack(a)
        else:self._send(t.origin,a.host,64,"cancel",a)

    def _ack(self,a,lease=False):
        if a.lifecycle.state in {AttemptState.COMPLETED,AttemptState.COMMITTED,AttemptState.LATE_RESULT_DISCARDED,AttemptState.CANCELLED,AttemptState.FAILED}:
            return
        task=self.tasks[a.task_uid]
        if self.models and not a.degraded and self.now>=task.deadline:
            observed=a.observed_resource or self.resource(a.host)
            self.models.observe(task,self.devices[a.host],observed,a.compute_time_us,False,latency_observed=False)
            self.emit("PRIVATE_OBSERVATION",task=task,attempt=a,device=a.host,
                      features=self.models.features(task,self.devices[a.host],observed).tolist()[0],
                      service_time_us=a.compute_time_us,execution_on_time=False,
                      latency_censored=True,scope="deadline_execution_failure_not_completed_latency")
        self._remove(a)
        if lease and a.lifecycle.state not in {AttemptState.CANCEL_REQUESTED,AttemptState.CANCELLED}:
            a.lifecycle.request_cancel()
        if a.lifecycle.state is AttemptState.CANCEL_REQUESTED:a.lifecycle.acknowledge_cancel(self.now)
        a.phase="CANCELLED"
        self.emit("ATTEMPT_LEASE_EXPIRED" if lease else "CANCEL_ACK",task=self.tasks[a.task_uid],attempt=a,device=a.host,wasted_work_us=a.work_done)

    def _miss(self,t,reason):
        if t.status in {"COMMITTED","MISSED","SKIPPED"}:return
        t.status="MISSED"
        self.emit("TASK_DEADLINE",task=t,critical=t.critical,reason=reason)
        for a in self.attempts.values():
            if a.task_uid==t.uid:self._cancel(a,reason)
        self._drop(self.jobs[t.job_id],"predecessor_failed")

    def _drop(self,j,reason):
        if j.status!="ACTIVE":return
        j.status="MISSED"
        self.emit("JOB_MISS",device=j.origin,job=j.uid,workflow=j.workflow.pipeline_id,reason=reason)
        for t in j.tasks.values():
            if t.status=="BLOCKED":
                t.status="SKIPPED";self.emit("TASK_SKIPPED",task=t,reason=reason)
            elif t.status not in {"COMMITTED","MISSED","SKIPPED"}:
                t.status="MISSED";self.emit("TASK_DEADLINE",task=t,critical=t.critical,reason="job_dropped")
                for a in self.attempts.values():
                    if a.task_uid==t.uid:self._cancel(a,reason)
        for uid,op in list(self.operations.items()):
            if op.payload.get("task") in {t.uid for t in j.tasks.values()}:
                if self.cpu[op.host]==uid:self.cpu[op.host]=None
                del self.operations[uid]

    def _queue_bound(self,host,gpu,exclude=None):
        return sum(self._work_bound(host,max(0,self.tasks[a.task_uid].spec.wcet_distribution.wcet_us-a.work_done),gpu)
                   for a in self.attempts.values() if a.host==host and a.task_uid!=exclude
                   and self.tasks[a.task_uid].gpu==gpu and a.phase in {"QUEUED","RUNNING","CANCEL_PENDING"})

    def _tail_bound(self,t):
        j=self.jobs[t.job_id];desc={t.spec.task_id};changed=True
        while changed:
            changed=False
            for source,target in j.workflow.dependency_edges:
                if source in desc and target not in desc:desc.add(target);changed=True
        return sum(self._work_bound(t.origin,s.spec.wcet_distribution.wcet_us,s.gpu)
                   for name,s in j.tasks.items() if name in desc and name!=t.spec.task_id and s.status!="COMMITTED")

    def _exit(self,t,elapsed=0):
        if not self.enable_fallback:return None
        for point in sorted(t.spec.exit_points,key=lambda p:(-p.output_utility,p.remaining_wcet_us,p.checkpoint_id)):
            if point.structurally_valid and point.elapsed_work_interval_us[0]<=elapsed<=point.elapsed_work_interval_us[1]:
                from rts_predictive.verification.live_fallback import analyze_fallback
                certificate=analyze_fallback(self,t,point)
                self.emit("FALLBACK_ANALYSIS",task=t,**certificate)
                if certificate['status']=='VERIFIED':
                    self._fallback_candidates[t.uid]=certificate
                    return point
        return None

    def _admit_fallback(self,t,a,point):
        from rts_predictive.verification.live_fallback import analyze_fallback
        certificate=self._fallback_candidates.get(t.uid)
        if not certificate or certificate['at_us']!=self.now or certificate['checkpoint_id']!=point.checkpoint_id:
            certificate=analyze_fallback(self,t,point)
            self.emit("FALLBACK_ANALYSIS",task=t,**certificate)
        if certificate['status']!='VERIFIED':raise ValueError("fallback admission requires a matching live certificate")
        self._fallback_sequence+=1
        a.fallback_order=self._fallback_sequence;a.fallback_certificate=certificate;a.exit_checkpoint=point.checkpoint_id
        self.emit("FALLBACK_ADMITTED",task=t,attempt=a,admission_order=a.fallback_order,
                  certificate_sha256=certificate['certificate_sha256'],checkpoint_id=point.checkpoint_id,
                  response_bound_us=certificate['response_bound_us'])

    def _link_bound(self,source,target,size):
        r=self.resource(source);q=self.resource(target)
        service=ceil_div(size*8,self.devices[source].bandwidth_mbps)
        return (max(0,self.radio[source]-self.now)+service+self.config.base_link_us+self.config.jitter_us+
                max(r["link_extra_us"],q["link_extra_us"]))

    def _candidates(self,t):
        results=[]
        for host,d in self.devices.items():
            if host==t.origin:continue
            r=self.resource(host)
            if self.models:
                try:
                    if hasattr(self.models,"last_estimate_evidence"):self.models.last_estimate_evidence=None
                    estimate,execution_reliability=self.models.estimate(t,d,r)
                    recorded=getattr(self.models,"last_estimate_evidence",None)
                    evidence=recorded[2] if recorded and recorded[:2]==(t.uid,host) else None
                    if (type(estimate) is not int or estimate<1 or isinstance(execution_reliability,bool) or
                        not isinstance(execution_reliability,(int,float)) or not math.isfinite(execution_reliability) or
                        not 0<=execution_reliability<=1):
                        raise ValueError("remote estimator returned invalid latency or reliability")
                except Exception as exc:
                    results.append({"device":host,"bound_us":None,"predicted_reliability":None,"accepted":False,
                                    "reason":"estimator_unavailable","error_type":type(exc).__name__,"error":str(exc),
                                    "estimator_version":self.models.version})
                    continue
            else:estimate,execution_reliability=0,1.0;evidence=None
            loss=max(r["loss_ppm"],self.resource(t.origin)["loss_ppm"])/PPM
            delivery_reliability=(1-loss**(self.config.retry_limit+1))**2
            reliability=execution_reliability*delivery_reliability
            execution=max(estimate,self._work_bound(host,t.spec.wcet_distribution.wcet_us,t.gpu))
            bound=self._link_bound(t.origin,host,t.spec.request_payload_bytes)+self._queue_bound(host,t.gpu)+execution+self._link_bound(host,t.origin,t.spec.result_payload_bytes)
            memory_ok=r["memory_mb"]+self._memory(t)<=d.memory_mb
            accepted=memory_ok and reliability>=.65 and self.now+bound+self.config.margin_us<=t.deadline
            reason="admitted" if accepted else ("memory" if not memory_ok else "reliability" if reliability<.65 else "deadline")
            candidate={"device":host,"bound_us":bound,"predicted_reliability":reliability,"accepted":accepted,
                            "predicted_execution_reliability":execution_reliability,
                            "analytical_delivery_reliability":delivery_reliability,
                            "reason":reason,"estimator_version":self.models.version if self.models else None}
            if evidence:
                candidate["estimator_evidence"]={**evidence,"at_us":self.now,
                                               "model_age_us":self.now-self.estimator_published_us}
            results.append(candidate)
        return results

    def _decide(self,t,existing=None):
        if not self.neural:
            self._baseline_decide(t,existing)
            return
        active=[s for s in self.tasks.values() if s.origin==t.origin and s.status not in {"COMMITTED","SKIPPED","MISSED"}]
        started=time.perf_counter_ns()
        try:
            prediction=self.models.predict(t,active,self.resource(t.origin),self.now)
            probability=prediction["miss_probability"]
            if isinstance(probability,bool) or not isinstance(probability,(int,float)) or not math.isfinite(probability) or not 0<=probability<=1:
                raise ValueError("predictor returned an invalid miss probability")
        except Exception as exc:
            latency=max(1,(time.perf_counter_ns()-started)//1000)
            self.emit("HOST_INFERENCE",task=t,latency_us=latency,evidence="MEASURED_ON_HOST",
                      budget_us=self.config.host_inference_budget_us,overrun=latency>self.config.host_inference_budget_us,
                      enforcement=self.config.enforce_host_inference_budget,failed=True,
                      scope="failed inference call; observed not proven WCET")
            self.emit("PREDICTOR_UNAVAILABLE",task=t,error_type=type(exc).__name__,reason=str(exc),
                      model_version=getattr(self.models.gnn,"bundle_version","unknown"),
                      fallback="reactive_local_degradation_or_full_local")
            self._baseline_decide(t,existing,fail_safe=True)
            return
        latency=prediction.pop("host_latency_us",None)
        if latency is not None:
            overrun=latency>self.config.host_inference_budget_us
            self.emit("HOST_INFERENCE",task=t,latency_us=latency,evidence="MEASURED_ON_HOST",
                      budget_us=self.config.host_inference_budget_us,overrun=overrun,
                      enforcement=self.config.enforce_host_inference_budget,
                      scope="graph construction and forward; excludes serialization; observed not proven WCET")
            if overrun:
                self.emit("INFERENCE_BUDGET_OVERRUN",task=t,latency_us=latency,
                          budget_us=self.config.host_inference_budget_us,
                          recommendation_discarded=self.config.enforce_host_inference_budget)
                if self.config.enforce_host_inference_budget:
                    self._baseline_decide(t,existing)
                    return
        self.emit("PREDICTION",task=t,**prediction)
        elapsed=self.attempts[existing].work_done if existing else 0
        own=max(0,t.spec.wcet_distribution.wcet_us-elapsed)
        local=self._queue_bound(t.origin,t.gpu,t.uid)+self._work_bound(t.origin,own,t.gpu)
        end_to_end=self.now+local+self._tail_bound(t)>self.jobs[t.job_id].deadline
        risk_gate=prediction["miss_probability"]>=self.models.gnn.decision_threshold
        local_guard=self.now+local+self.config.margin_us>t.deadline
        high=risk_gate or local_guard or end_to_end
        candidates=self._candidates(t) if high and t.spec.offloadable and self.enable_offload and not existing else []
        feasible=[c for c in candidates if c["accepted"]]
        exit_point=self._exit(t,elapsed) if high else None
        action="LOCAL"
        if feasible:
            target=min(feasible,key=lambda c:(c["bound_us"],c["device"]))["device"]
            action="OFFLOAD";self._new_attempt(t,target)
        elif exit_point:
            action="EARLY_EXIT";t.degraded=True
            if existing:
                a=self.attempts[existing];a.degraded=True;a.utility=exit_point.output_utility
                a.remaining=exit_point.remaining_wcet_us+exit_point.checkpoint_overhead_us
                a.total=a.work_done+a.remaining;a.layer_end=a.total;a.phase="QUEUED";a.queued=True
                self._admit_fallback(t,a,exit_point)
            else:self._new_attempt(t,t.origin,True,exit_point)
            self.emit("EARLY_EXIT",task=t,checkpoint=exit_point.checkpoint_id,
                      remaining_work_us=exit_point.remaining_wcet_us,checkpoint_overhead_us=exit_point.checkpoint_overhead_us,
                      utility=exit_point.output_utility)
        elif existing:
            a=self.attempts[existing];a.phase="QUEUED";a.queued=True;t.status="QUEUED"
        else:self._new_attempt(t,t.origin)
        self.emit("DECISION",task=t,action=action,prediction=prediction["miss_probability"],
                  feasibility_guard=end_to_end,local_bound_us=local,candidates=candidates,
                  threshold=self.models.gnn.decision_threshold,risk_gate=risk_gate,
                  local_deadline_guard=local_guard,high_risk=high,deadline_margin_us=self.config.margin_us)

    def _baseline_decide(self,t,existing,fail_safe=False):
        """Non-neural comparators use the same execution and communication kernel."""
        elapsed=self.attempts[existing].work_done if existing else 0
        local=self._queue_bound(t.origin,t.gpu,t.uid)+self._work_bound(t.origin,max(0,t.spec.wcet_distribution.wcet_us-elapsed),t.gpu)
        candidates=[];action="LOCAL"
        if self.policy=="always_offload" and t.spec.offloadable and not existing and self.enable_offload:
            candidates=self._candidates(t)
            eligible=[c for c in candidates if c["reason"]!="memory"]
            if eligible:
                peer=min(eligible,key=lambda c:(c["bound_us"],c["device"]))
                action="OFFLOAD";self._new_attempt(t,peer["device"])
        point=self._exit(t,elapsed) if (self.policy=="reactive" or self.config.enforce_host_inference_budget or fail_safe) and self.now+local+self.config.margin_us>t.deadline else None
        if point:
            action="EARLY_EXIT"
            if existing:
                a=self.attempts[existing];a.degraded=True;a.utility=point.output_utility
                a.remaining=point.remaining_wcet_us+point.checkpoint_overhead_us
                a.total=a.work_done+a.remaining;a.layer_end=a.total;a.phase="QUEUED";a.queued=True;t.degraded=True
                self._admit_fallback(t,a,point)
            else:self._new_attempt(t,t.origin,True,point)
            self.emit("EARLY_EXIT",task=t,checkpoint=point.checkpoint_id,remaining_work_us=point.remaining_wcet_us,
                      checkpoint_overhead_us=point.checkpoint_overhead_us,utility=point.output_utility)
        elif action=="LOCAL":
            if existing:self.attempts[existing].phase="QUEUED";self.attempts[existing].queued=True
            else:self._new_attempt(t,t.origin)
        self.emit("DECISION",task=t,action=action,prediction=None,local_bound_us=local,candidates=candidates,comparator=self.policy,
                  **({"predictor_unavailable":True} if fail_safe else {}))

    def _watchdog(self,t):
        if t.status in {"COMMITTED","MISSED","SKIPPED"} or self.jobs[t.job_id].status!="ACTIVE":return
        a=self.attempts.get(t.current_attempt)
        if not a or a.host==t.origin:return
        remaining=max(0,t.spec.wcet_distribution.wcet_us-a.work_done)
        bound=self._queue_bound(a.host,t.gpu,t.uid)+self._work_bound(a.host,remaining,t.gpu)+self._link_bound(a.host,t.origin,t.spec.result_payload_bytes)
        if a.phase=="RESULT_TX":
            arrivals=[tx["end_us"] for tx in self.transfers.values() if tx["attempt"]==a.lifecycle.attempt_id and tx["kind"]=="result"]
            bound=max(0,max(arrivals,default=self.now)-self.now)
        if a.phase=="REQUEST_TX":bound+=max(0,a.request_arrival_us-self.now)
        failed=self._failed_remote_transfers.get(a.lifecycle.attempt_id)
        point=self._exit(t,0)
        recovery=self._fallback_candidates[t.uid]['response_bound_us'] if point else None
        latest=t.deadline-recovery-self.config.margin_us if recovery is not None else None
        remote_late=self.now+bound+self.config.margin_us>t.deadline
        window_closing=point is not None and self.now+self.config.watchdog_period_us>=latest
        abort=bool(point and (failed or remote_late or window_closing))
        reason=("no_admissible_fallback" if point is None else "remote_transfer_failed" if failed else
                "remote_bound_exceeds_deadline" if remote_late else "fallback_window_closing" if window_closing else "remote_within_window")
        self.emit("WATCHDOG_CHECK",task=t,attempt=a,target=a.host,remote_bound_us=None if failed else bound,
                  recovery_bound_us=recovery,latest_abort_us=latest,action="ABORT" if abort else "CONTINUE",
                  reason=reason,remote_transfer_failed=failed,margin_us=self.config.margin_us,
                  next_check_us=self.now+self.config.watchdog_period_us)
        if abort:
            self.emit("WATCHDOG_ABORT",task=t,attempt=a,target=a.host)
            self._cancel(a,"watchdog_recovery")
            self._new_attempt(t,t.origin,True,point)
            self.emit("EARLY_EXIT",task=t,checkpoint=point.checkpoint_id,remaining_work_us=point.remaining_wcet_us,
                      checkpoint_overhead_us=point.checkpoint_overhead_us,utility=point.output_utility)
        else:self.push(self.now+self.config.watchdog_period_us,"WATCHDOG",t.uid)

    def _send(self,source,target,size,kind,a=None,payload=None,retry=0):
        if a:a.lifecycle.charge(network_bytes=size)
        self._tx_sequence+=1;uid=f"tx-{self._tx_sequence}"
        start=max(self.now,self.radio[source]);serialization=max(1,ceil_div(size*8,self.devices[source].bandwidth_mbps))
        self.radio[source]=start+serialization
        key=f"research/link/{a.task_uid if a else payload['round']}/{source}/{target}/{kind}/{retry}"
        rng=random.Random(derive_stream_seed(self.config.seed,key))
        src,dst=self.resource(source),self.resource(target)
        arrival=start+serialization+self.config.base_link_us+rng.randint(0,self.config.jitter_us)+max(src["link_extra_us"],dst["link_extra_us"])
        loss=rng.randrange(PPM)<max(src["loss_ppm"],dst["loss_ppm"])
        transfer={"id":uid,"source":source,"target":target,"kind":kind,"bytes":size,"start_us":start,
                  "end_us":arrival,"attempt":a.lifecycle.attempt_id if a else None,"payload":payload,"retry":retry,"loss":loss}
        self.transfers[uid]=transfer
        if a and kind=="request":a.request_arrival_us=arrival
        self.emit("TX_START",task=self.tasks[a.task_uid] if a else None,attempt=a,device=source,
                  transfer=uid,target=target,phase=kind,bytes=size,start_us=start,end_us=arrival,retry=retry)
        self.push(arrival,"DELIVER",uid)

    def _deliver(self,uid):
        tx=self.transfers.pop(uid);a=self.attempts.get(tx["attempt"])
        t=self.tasks[a.task_uid] if a else None
        if tx["loss"]:
            self.emit("PACKET_LOSS",task=t,attempt=a,device=tx["source"],transfer=uid,phase=tx["kind"])
            if tx["retry"]<self.config.retry_limit:
                self._send(tx["source"],tx["target"],tx["bytes"],tx["kind"],a,tx["payload"],tx["retry"]+1)
            else:
                self.emit("TRANSFER_FAILED",task=t,attempt=a,device=tx["source"],phase=tx["kind"])
                if a and tx["kind"] in {"request","result"}:
                    self._failed_remote_transfers[a.lifecycle.attempt_id]=tx["kind"]
                if tx["kind"]=="cancel":
                    self.emit("CANCEL_UNDELIVERED",task=t,attempt=a,device=tx["source"])
                elif tx["kind"].startswith("fl_"):self._fl_delivery(tx,False)
            return
        self.emit("TX_END",task=t,attempt=a,device=tx["target"],transfer=uid,phase=tx["kind"])
        if tx["kind"]=="request":
            if a.lifecycle.state not in {AttemptState.CANCELLED,AttemptState.LATE_RESULT_DISCARDED,AttemptState.FAILED}:
                a.phase="QUEUED";a.queued=True
                self.emit("REMOTE_ADMIT",task=t,attempt=a,device=a.host,total_work_us=a.total)
            else:self.emit("LATE_RESULT_DISCARDED",task=t,attempt=a)
        elif tx["kind"]=="result":self._commit(t,a)
        elif tx["kind"]=="cancel":self._ack(a)
        else:self._fl_delivery(tx,True)

    def _start_fl(self):
        if self.now>=self.config.release_end_us:return
        if not self.fl_round:
            self.fl_rounds+=1
            participants=[host for host in self.devices if len(self.models.private.get(host,[]))>=4]
            if len(participants)>=2:
                self.fl_round={"id":self.fl_rounds,"participants":participants,"uploads":{},"downloads":{}}
                self.emit("FL_ROUND_START",round=self.fl_rounds,participants=participants,coordinator=self.fl_coordinator)
                for host in participants:
                    records=tuple(self.models.private[host]);count=len(records)
                    self.emit("FL_TRAIN_START",device=host,round=self.fl_rounds,samples=count)
                    self._op(host,"fl_train",count*self.config.training_work_us_per_sample,
                             self.config.end_us+1,{"round":self.fl_rounds,"samples":count,"records":records})
            else:self.emit("FL_ROUND_SKIPPED",round=self.fl_rounds,reason="insufficient_private_samples")
        if self.now+self.config.fl_period_us<self.config.release_end_us:self.push(self.now+self.config.fl_period_us,"FL_ROUND")

    def _fl_trained(self,op):
        if not self.fl_round:return
        started=time.perf_counter_ns()
        try:
            update=self.models.train(op.host,self.now,op.payload["records"])
            from rts_predictive.predictors.research_adapter import ResearchModels
            expected=self.models.remote.state_dict()
            ResearchModels.validate_update(update,expected,len(op.payload['records']))
        except Exception as exc:
            self.emit("HOST_TRAIN",device=op.host,latency_us=max(1,(time.perf_counter_ns()-started)//1000),
                      evidence="MEASURED_ON_HOST",failed=True)
            self.emit("FL_TRAIN_FAILED",device=op.host,round=self.fl_round['id'],
                      error_type=type(exc).__name__,reason=str(exc))
            self._fl_delivery({'kind':'fl_upload','payload':{'round':self.fl_round['id'],'host':op.host}},False)
            return
        observation=self.models.host_observations[-1]
        self.emit("HOST_TRAIN",device=op.host,latency_us=observation["latency_us"],evidence="MEASURED_ON_HOST")
        self.emit("FL_TRAIN_END",device=op.host,round=self.fl_round["id"],samples=update["samples"],loss=update["loss"])
        payload={"round":self.fl_round["id"],"host":op.host,"update":update}
        if op.host==self.fl_coordinator:
            self.emit("FL_LOCAL_UPDATE",device=op.host,round=self.fl_round["id"])
            self._fl_delivery({"kind":"fl_upload","payload":payload},True)
        else:self._send(op.host,self.fl_coordinator,update["bytes"],"fl_upload",payload=payload)

    def _fl_delivery(self,tx,success):
        if not self.fl_round or tx["payload"]["round"]!=self.fl_round["id"]:return
        if tx["kind"]=="fl_upload":
            self.fl_round["uploads"][tx["payload"]["host"]]=tx["payload"]["update"] if success else None
            if len(self.fl_round["uploads"])==len(self.fl_round["participants"]):
                if sum(u is not None for u in self.fl_round["uploads"].values())>=2:
                    self._op(self.fl_coordinator,"fl_aggregate",self.config.aggregation_cost_us,self.config.end_us+1,{})
                else:self.emit("FL_ROUND_SKIPPED",round=self.fl_round["id"],reason="insufficient_delivered_updates");self.fl_round=None
        else:
            self.fl_round["downloads"][tx["payload"]["host"]]=success
            if len(self.fl_round["downloads"])==len(self.fl_round["participants"]):
                if all(self.fl_round["downloads"].values()):
                    updates=[u for u in self.fl_round["uploads"].values() if u]
                    previous=deepcopy(self.models.remote)
                    previous_version=self.models.version
                    previous_digest=getattr(self.models,"parameter_sha256",None)
                    try:version,digest=self.models.publish(updates)
                    except Exception as exc:
                        self.models.remote=previous;self.models.version=previous_version
                        if previous_digest is not None:self.models.parameter_sha256=previous_digest
                        self.emit("FL_ROUND_SKIPPED",round=self.fl_round["id"],reason="aggregation_failure",error_type=type(exc).__name__,error=str(exc))
                        self.fl_round=None
                        return
                    self.estimator_published_us=self.now
                    self.emit("MODEL_PUBLISH",round=self.fl_round["id"],version=version,weights_sha256=digest,
                              samples=sum(u["samples"] for u in updates),participants=len(updates),
                              reliability_calibrated=False,latency_coverage_validated=False)
                else:self.emit("FL_ROUND_SKIPPED",round=self.fl_round["id"],reason="incomplete_model_download")
                self.fl_round=None

    def _fl_aggregate(self):
        if not self.fl_round:return
        updates=[u for u in self.fl_round["uploads"].values() if u]
        self.emit("FL_AGGREGATE",round=self.fl_round["id"],samples=sum(u["samples"] for u in updates),participants=len(updates))
        for host in self.fl_round["participants"]:
            payload={"round":self.fl_round["id"],"host":host}
            if host==self.fl_coordinator:self._fl_delivery({"kind":"fl_download","payload":payload},True)
            else:self._send(self.fl_coordinator,host,updates[0]["bytes"],"fl_download",payload=payload)

    def sample(self):
        for host in self.devices:
            resource=self.resource(host)
            work=[{"attempt":a.lifecycle.attempt_id,"task":a.task_uid,"phase":a.phase,
                   "work_done_us":a.work_done,"total_work_us":a.total,"remaining_us":a.remaining,
                   "layer":a.layer,"degraded":a.degraded,"host":a.host}
                  for a in self.attempts.values() if a.host==host and a.phase in {"QUEUED","RUNNING","CANCEL_PENDING","CHECKPOINT","REQUEST_TX","RESULT_TX"}]
            self.emit("RESOURCE_SAMPLE",device=host,**resource,cpu_slot=self.cpu[host],gpu_slot=self.gpu[host],attempts=work,
                      operations=[{"id":op.uid,"kind":op.kind,"remaining_us":op.remaining,"deadline_us":op.deadline,"task":op.payload.get("task")} for op in self.operations.values() if op.host==host])
