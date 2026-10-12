"""Incremental canonical-event reducer for the research laboratory."""
from collections import Counter
from copy import deepcopy
from rts_predictive.dashboard.learning_projection import LearningProjection


class ResearchProjection:
    def __init__(self):
        self.jobs={};self.tasks={};self.resources={};self.attempts={};self.transfers={}
        self.decisions={};self.predictions={};self.watchdogs={};self.fl={"phase":"waiting","version":0}
        self.counts=Counter();self.log=[];self.overhead=Counter();self.responses=[]
        self.now=0;self.done=False;self._sequence=0
        self.network_bytes=0
        self.host_latencies=[]
        self.discarded_inferences=0
        self.handoffs={}
        self.offload_attempts=set()
        self.service_work=Counter()
        self.learning=LearningProjection()

    def consume(self,e):
        if e["sequence"]<=self._sequence or e["timestamp_us"]<self.now:raise ValueError("event order violation")
        self._sequence=e["sequence"];self.now=e["timestamp_us"]
        k,p,tid,jid,aid=e["event_type"],e["payload"],e.get("task_id"),e.get("job_id"),e.get("attempt_id")
        self.counts[k]+=1
        self.learning.consume(e)
        if k=="OFFLOAD_DISPATCH":
            self.offload_attempts.add(aid)
            self.handoffs[aid]={"id":aid,"task":tid,"job":jid,"origin":e["device_id"],
                                "target":p["target"],"start_us":self.now,"state":"REQUEST","events":[]}
        # Keep canonical milestones after short-lived transfers disappear from the live graph.
        if tid and k in {"OFFLOAD_DISPATCH","TX_START","TX_END","PACKET_LOSS","REMOTE_ADMIT",
                         "EXECUTION_START","CHECKPOINT","EXECUTION_COMPLETE","WATCHDOG_CHECK",
                         "WATCHDOG_ABORT","CANCEL_REQUEST","CANCEL_ACK","ATTEMPT_LEASE_EXPIRED",
                         "EARLY_EXIT","ATTEMPT_CREATED","TASK_COMMIT","TASK_DEADLINE","LATE_RESULT_DISCARDED","CANCEL_UNDELIVERED","PREEMPT","TRANSFER_FAILED",
                         "FALLBACK_ANALYSIS","FALLBACK_ADMITTED","FALLBACK_BOUND_CHECK","OUTPUT_VALIDATION","OUTPUT_REJECTED"}:
            for h in self.handoffs.values():
                if h["task"]!=tid:continue
                h["events"].append(e)
                if k=="WATCHDOG_ABORT":h["state"]="RECOVERING"
                elif k=="TASK_COMMIT":h["state"]="RETURNED" if aid==h["id"] else "RECOVERED"
                elif k=="TASK_DEADLINE":h["state"]="MISSED"
                elif k=="REMOTE_ADMIT" and h["state"]=="REQUEST":h["state"]="REMOTE"
        if k=="JOB_RELEASE":self.jobs[jid]={"id":jid,"device":e["device_id"],"release_us":self.now,"status":"ACTIVE",**p}
        elif k=="JOB_COMPLETE":self.jobs[jid].update(status="COMPLETE",terminal_us=self.now,**p)
        elif k=="JOB_MISS":self.jobs[jid].update(status="MISSED",terminal_us=self.now,**p)
        elif k=="TASK_PLANNED":self.tasks[tid]={"id":tid,"job":jid,"device":e["device_id"],"state":"BLOCKED",**p}
        elif k=="TASK_READY":self.tasks[tid].update(state="DECIDING",ready_us=self.now,**p)
        elif k in {"TASK_COMMIT","TASK_DEADLINE","TASK_SKIPPED"}:
            self.tasks[tid].update(state={"TASK_COMMIT":"COMMITTED","TASK_DEADLINE":"MISSED","TASK_SKIPPED":"SKIPPED"}[k],terminal_us=self.now,**p)
            if k=="TASK_DEADLINE" and p.get("reason")!="job_dropped":
                job=self.jobs[jid]
                if "failure_task" not in job:job.update(failure_task=tid,failure_us=self.now,failure_reason=p.get("reason"))
            if k=="TASK_COMMIT":
                self.tasks[tid].update(committed_attempt=aid,commit_us=self.now)
                self.responses.append(p["response_time_us"])
                self.attempts.setdefault(aid,{"id":aid,"task":tid}).update(state="COMMITTED",phase="COMMITTED")
        elif k=="OFFLOAD_DISPATCH":
            self.tasks[tid].update(state="OFFLOADED",host=p["target"],attempt=aid)
            self.tasks[tid].setdefault("handoff_ids",[]).append(aid)
            self.attempts.setdefault(aid,{"id":aid,"task":tid}).update(host=p["target"],state="REQUEST_TX",phase="REQUEST_TX")
        elif k=="SERVICE":
            # Sampling can stop before an attempt is cancelled. Reconstruct its
            # exact delivered work from service events, not its last live sample.
            self.service_work[aid]+=p["work_us"]
            a=self.attempts[aid]
            a["work_done_us"]=self.service_work[aid]
            if "total_work_us" in a:
                a["remaining_us"]=a["total_work_us"]-a["work_done_us"]
        elif k in {"ATTEMPT_CREATED","EXECUTION_START","REMOTE_ADMIT","CHECKPOINT","EXECUTION_COMPLETE","CANCEL_REQUEST","CANCEL_ACK","ATTEMPT_LEASE_EXPIRED","PREEMPT"}:
            a=self.attempts.setdefault(aid,{"id":aid,"task":tid})
            a.update(**p,host=p["target"] if k=="CANCEL_REQUEST" else e["device_id"],updated_us=self.now)
            if "total_work_us" in a:
                a.setdefault("work_done_us",self.service_work[aid])
                a["remaining_us"]=a["total_work_us"]-a["work_done_us"]
            if k=="EXECUTION_COMPLETE":a.update(work_done_us=p["work_us"],remaining_us=0)
            a["state"]={"ATTEMPT_CREATED":"QUEUED","EXECUTION_START":"RUNNING","REMOTE_ADMIT":"QUEUED",
                        "CHECKPOINT":"CHECKPOINT","EXECUTION_COMPLETE":"COMPLETED","CANCEL_REQUEST":"CANCEL_PENDING",
                        "CANCEL_ACK":"CANCELLED","ATTEMPT_LEASE_EXPIRED":"CANCELLED","PREEMPT":"QUEUED"}[k]
            a["phase"]=a["state"]
            if k=="CANCEL_REQUEST":a["cancel_requested_us"]=self.now
            if k in {"ATTEMPT_CREATED","PREEMPT","REMOTE_ADMIT"} and self.tasks[tid]["state"] not in {"COMMITTED","MISSED","SKIPPED"}:
                current=self.tasks[tid].get("attempt")
                if k=="ATTEMPT_CREATED" or current in (None,aid):
                    self.tasks[tid].update(state="QUEUED",host=a["host"],attempt=aid,degraded=p.get("degraded",False))
            if k=="EXECUTION_START" and p.get("current_attempt",True) and self.tasks[tid]["state"] not in {"COMMITTED","MISSED","SKIPPED"}:
                self.tasks[tid].setdefault("first_start_us",self.now)
                self.tasks[tid].update(state="RUNNING",host=e["device_id"],attempt=aid,degraded=p["degraded"])
        elif k=="EARLY_EXIT":self.tasks[tid].update(degraded=True,**p)
        elif k in {"FALLBACK_ANALYSIS","FALLBACK_ADMITTED","FALLBACK_BOUND_CHECK","OUTPUT_VALIDATION","OUTPUT_REJECTED","HOST_INFERENCE","INFERENCE_BUDGET_OVERRUN"} and tid:
            if k!='OUTPUT_VALIDATION' or self.tasks[tid].get('attempt') in (None,aid):
                self.tasks[tid][k.lower()]={"at_us":self.now,**p}
            if k=='OUTPUT_VALIDATION':self.attempts.setdefault(aid,{'id':aid,'task':tid})['output_validation']={"at_us":self.now,**p}
            if k=="HOST_INFERENCE":self.host_latencies.append(p['latency_us'])
            if k=="INFERENCE_BUDGET_OVERRUN" and p['recommendation_discarded']:self.discarded_inferences+=1
        elif k=="PREDICTION":self.predictions[tid]={"task":tid,"device":e["device_id"],"at_us":self.now,**p}
        elif k=="PREDICTOR_UNAVAILABLE":
            self.predictions.pop(tid,None)
            self.tasks[tid]["predictor_unavailable"]={"at_us":self.now,**p}
        elif k=="DECISION":self.decisions[tid]={"task":tid,"device":e["device_id"],"at_us":self.now,**p}
        elif k in {"WATCHDOG_CHECK","WATCHDOG_ABORT"}:self.watchdogs[tid]={**self.watchdogs.get(tid,{}),"task":tid,"at_us":self.now,**p}
        elif k=="TX_START":
            self.transfers[p["transfer"]]={"id":p["transfer"],"source":e["device_id"],"task":tid,"attempt":aid,**p}
            self.network_bytes+=p["bytes"]
        elif k in {"TX_END","PACKET_LOSS"}:self.transfers.pop(p["transfer"],None)
        elif k=="RESOURCE_SAMPLE":
            self.resources[e["device_id"]]={"at_us":self.now,**p}
            for a in p["attempts"]:
                self.attempts.setdefault(a["attempt"],{"id":a["attempt"],"task":a["task"]}).update(**a)
                t=self.tasks[a["task"]]
                if t.get("attempt")==a["attempt"] and t["state"] not in {"COMMITTED","MISSED","SKIPPED"}:
                    state={"QUEUED":"QUEUED","RUNNING":"RUNNING","CHECKPOINT":"DECIDING","REQUEST_TX":"OFFLOADED"}.get(a["phase"])
                    if state:t.update(state=state)
        elif k=="CPU_OVERHEAD":self.overhead[p["category"]]+=p["work_us"]
        elif k=="HOST_INFERENCE":self.host_latencies.append(p["latency_us"])
        elif k.startswith("FL_"):self.fl.update(phase=k,**p)
        elif k=="MODEL_PUBLISH":self.fl.update(phase="MODEL_PUBLISH",**p)
        elif k=="RUN_COMPLETE":self.done=True
        if k not in {"SERVICE","CPU_OVERHEAD","RESOURCE_SAMPLE","TASK_PLANNED"}:
            self.log.append(e)
            del self.log[:-100]

    def metrics(self):
        n=len(self.jobs);missed=sum(j["status"]=="MISSED" for j in self.jobs.values())
        completed=sum(j["status"]=="COMPLETE" for j in self.jobs.values())
        ready=[t for t in self.tasks.values() if "ready_us" in t]
        met=[t for t in ready if t["state"]=="COMMITTED"]
        failed=[t for t in ready if t["state"]=="MISSED"]
        critical=[t for t in ready if t["critical"]]
        failed_critical=[t for t in critical if t["state"]=="MISSED"]
        offloads=[self.attempts[aid] for aid in self.offload_attempts]
        returned=[a for a in offloads if a.get("phase")=="COMMITTED"]
        mean=sum(self.responses)/len(self.responses) if self.responses else None
        return {"released_jobs":n,"missed_jobs":missed,"completed_jobs":completed,"pending_jobs":n-completed-missed,
                "job_dmr_pct":100*missed/n if n else None,"ready_tasks":len(ready),"missed_tasks":len(failed),
                "task_dmr_pct":100*len(failed)/len(ready) if ready else None,"committed_tasks":len(met),
                "mean_utility":sum(t.get("utility",1) for t in met)/len(met) if met else None,
                "max_task_response_us":max(self.responses) if self.responses else None,
                "mean_task_response_us":mean,
                "task_response_jitter_us":max(self.responses)-min(self.responses) if self.responses else None,
                "critical_ready_tasks":len(critical),"critical_missed_tasks":len(failed_critical),
                "critical_task_dmr_pct":100*len(failed_critical)/len(critical) if critical else None,
                "offload_committed_results":len(returned),
                "offload_success_pct":100*len(returned)/len(offloads) if offloads else None,
                "offloads":self.counts["OFFLOAD_DISPATCH"],"watchdog_checks":self.counts["WATCHDOG_CHECK"],
                "watchdog_aborts":self.counts["WATCHDOG_ABORT"],"early_exits":self.counts["EARLY_EXIT"],
                "gnn_inferences":self.counts["PREDICTION"]+self.discarded_inferences+self.counts["PREDICTOR_UNAVAILABLE"],"model_publications":self.counts["MODEL_PUBLISH"],
                "overhead_work_us":dict(self.overhead),"network_bytes":getattr(self,"network_bytes",0),
                "final":self.done,"evidence":"SIMULATED"}

    def snapshot(self):
        tasks=[]
        for tid,t in self.tasks.items():
            diagnostics={name:records[tid] for name,records in (("prediction",self.predictions),("decision",self.decisions),("watchdog",self.watchdogs)) if tid in records}
            tasks.append({**t,"diagnostics":diagnostics})
        return deepcopy({"time_us":self.now,"done":self.done,"metrics":self.metrics(),"jobs":list(self.jobs.values()),
                "tasks":tasks,"resources":self.resources,"attempts":list(self.attempts.values()),
                "transfers":list(self.transfers.values()),"decisions":sorted(self.decisions.values(),key=lambda v:v["at_us"])[-16:],
                "predictions":sorted(self.predictions.values(),key=lambda v:v["at_us"])[-16:],
                "watchdogs":sorted(self.watchdogs.values(),key=lambda v:v["at_us"])[-16:],
                "federated":self.fl,"learning":self.learning.snapshot(),"events":self.log[-30:],"handoffs":list(self.handoffs.values())[-48:],
                "handoff_history_total":len(self.handoffs),"handoff_history_limit":48})


def paired_comparison(before,after):
    a,b=before["job_dmr_pct"],after["job_dmr_pct"]
    delta=a-b if a is not None and b is not None else None
    return {"before_pct":a,"after_pct":b,"change_pp":delta,
            "relative_reduction_pct":100*delta/a if a not in (None,0) and delta is not None else None,
            "final":before["final"] and after["final"],"primary_endpoint":"end_to_end_job_deadline_miss_ratio"}
