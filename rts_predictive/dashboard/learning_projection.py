"""Learning inspection derived exclusively from canonical runtime events."""
from collections import Counter, OrderedDict
from copy import deepcopy

from rts_predictive.domain.learning import LEARNING_VIEW_SCHEMA_VERSION, RECENT_LEARNING_ROUND_LIMIT


class LearningProjection:
    def __init__(self):
        self.gnn = Counter()
        self.latest_prediction = None
        self.latest_failure = None
        self.clients = {}
        self.rounds = OrderedDict()
        self.active_round = None
        self.publication = None
        self.round_counts = Counter()
        self.queries_by_version = Counter()
        self.transfers = {}
        self.failed_transfers = {}
        self.bytes = Counter()
        self.now = 0

    def client(self, host):
        return self.clients.setdefault(host, {"device":host,"observations":0,"phase":"WAITING",
                                              "training_samples":None,"loss":None,"round":None})

    def consume(self, e):
        self.now=e["timestamp_us"]
        k,p,host=e["event_type"],e["payload"],e.get("device_id")
        if k=="PREDICTION":
            self.gnn["successful"]+=1
            self.latest_prediction={"task":e["task_id"],"at_us":self.now,"sequence":e["sequence"],
                                    "miss_probability":p["miss_probability"],"graph_sha256":p["graph_sha256"],
                                    "model_version":p["model_version"]}
        elif k=="PREDICTOR_UNAVAILABLE":
            self.gnn["failed"]+=1
            self.latest_failure={"task":e["task_id"],"at_us":self.now,**p}
        elif k=="INFERENCE_BUDGET_OVERRUN" and p["recommendation_discarded"]:
            self.gnn["discarded"]+=1
        elif k=="PRIVATE_OBSERVATION":
            client=self.client(host);client["observations"]+=1;client["last_observation_us"]=self.now
        elif k=="DECISION":
            for candidate in p.get("candidates",[]):
                if candidate.get("estimator_evidence"):
                    self.queries_by_version[candidate["estimator_version"]]+=1
        elif k=="FL_ROUND_START":
            self.active_round=p["round"]
            self.rounds[p["round"]]={"round":p["round"],"phase":"TRAINING","started_us":self.now,
                "coordinator":p.get("coordinator"),"participants":list(p["participants"]),
                "clients":{h:{"device":h,"phase":"WAITING","samples":None,"loss":None} for h in p["participants"]},
                "upload_bytes":0,"download_bytes":0,"events":[self.record(e)]}
            self.round_counts["started"]+=1
            self.trim()
        elif k=="TX_START" and p.get("phase","").startswith("fl_"):
            if self.active_round is None:return
            target=p["target"];upload=p["phase"]=="fl_upload";client_host=host if upload else target
            self.transfers[p["transfer"]]={"round":self.active_round,"host":client_host,
                "phase":p["phase"],"source":host,**p}
            self.bytes[p["phase"]]+=p["bytes"]
            round_=self.rounds[self.active_round]
            round_["upload_bytes" if upload else "download_bytes"]+=p["bytes"]
            self.set_client(round_,client_host,"UPLOAD" if upload else "DOWNLOAD",
                            transfer_start_us=p["start_us"],transfer_end_us=p["end_us"],retry=p["retry"])
            self.add_event(round_,e)
        elif k in {"TX_END","PACKET_LOSS"} and p.get("phase","").startswith("fl_"):
            transfer=self.transfers.pop(p["transfer"],None)
            if transfer is None:return
            round_=self.rounds.get(transfer["round"])
            if round_ is None:return
            upload=transfer["phase"]=="fl_upload"
            phase=("UPLOADED" if upload else "DOWNLOADED") if k=="TX_END" else ("UPLOAD_RETRYING" if upload else "DOWNLOAD_RETRYING")
            self.set_client(round_,transfer["host"],phase)
            if k=="PACKET_LOSS":self.failed_transfers[(transfer["source"],transfer["phase"])]=transfer
            self.add_event(round_,e)
        elif k=="TRANSFER_FAILED" and p.get("phase","").startswith("fl_"):
            transfer=self.failed_transfers.pop((host,p["phase"]),None)
            if transfer and transfer["round"] in self.rounds:
                round_=self.rounds[transfer["round"]]
                self.set_client(round_,transfer["host"],"UPLOAD_FAILED" if p["phase"]=="fl_upload" else "DOWNLOAD_FAILED")
                self.add_event(round_,e)
        elif k.startswith("FL_") or k=="MODEL_PUBLISH":
            round_id=p.get("round",self.active_round)
            round_=self.rounds.get(round_id)
            if k=="FL_ROUND_SKIPPED" and round_ is None:
                # Old skip events can lack an identifier. Preserve that absence.
                key=round_id if round_id is not None else "skip-"+str(e["sequence"])
                round_={"round":round_id,"phase":"SKIPPED","started_us":self.now,"participants":[],
                        "clients":{},"upload_bytes":0,"download_bytes":0,"events":[]}
                self.rounds[key]=round_;self.trim()
            if round_ is None:return
            self.add_event(round_,e)
            if k=="FL_TRAIN_START":self.set_client(round_,host,"TRAINING",samples=p["samples"],started_us=self.now)
            elif k=="FL_TRAIN_END":
                self.set_client(round_,host,"TRAINED",samples=p["samples"],loss=p["loss"],trained_us=self.now)
                round_["phase"]="COLLECTING"
            elif k=="FL_TRAIN_FAILED":self.set_client(round_,host,"TRAIN_FAILED",reason=p["reason"])
            elif k=="FL_LOCAL_UPDATE":self.set_client(round_,host,"UPLOADED")
            elif k=="FL_AGGREGATE":
                round_.update(phase="DISTRIBUTING",aggregation_us=self.now,samples=p["samples"],contributing_clients=p["participants"])
                coordinator=round_.get("coordinator")
                if coordinator in round_["clients"]:self.set_client(round_,coordinator,"DOWNLOADED")
            elif k=="MODEL_PUBLISH":
                self.publication={"at_us":self.now,"sequence":e["sequence"],**p}
                round_.update(phase="PUBLISHED",ended_us=self.now,version=p["version"],weights_sha256=p["weights_sha256"],samples=p["samples"])
                self.round_counts["published"]+=1;self.active_round=None
            elif k in {"FL_ROUND_SKIPPED","FL_ROUND_INCOMPLETE"}:
                phase="SKIPPED" if k=="FL_ROUND_SKIPPED" else "INCOMPLETE"
                round_.update(phase=phase,ended_us=self.now,reason=p.get("reason","run ended before publication"))
                self.round_counts[phase.lower()]+=1;self.active_round=None

    @staticmethod
    def record(e):
        return {"sequence":e["sequence"],"at_us":e["timestamp_us"],"event_type":e["event_type"],"device":e.get("device_id")}

    def add_event(self, round_, e):
        round_["events"].append(self.record(e))
        del round_["events"][:-64]

    def set_client(self, round_, host, phase, **fields):
        row=round_["clients"].setdefault(host,{"device":host,"samples":None,"loss":None})
        row.update(phase=phase,at_us=self.now,**fields)
        client=self.client(host)
        client.update(phase=phase,round=round_["round"],at_us=self.now)
        if "samples" in fields:client["training_samples"]=fields["samples"]
        if "loss" in fields:client.update(loss=fields["loss"],loss_at_us=self.now)

    def trim(self):
        while len(self.rounds)>RECENT_LEARNING_ROUND_LIMIT:self.rounds.popitem(last=False)

    def snapshot(self):
        gnn={name:self.gnn[name] for name in ("successful","failed","discarded")}
        gnn["attempts"]=sum(gnn.values())
        gnn.update(latest_prediction=self.latest_prediction,latest_failure=self.latest_failure)
        return deepcopy({"schema_version":LEARNING_VIEW_SCHEMA_VERSION,"at_us":self.now,"gnn":gnn,
            "clients":list(self.clients.values()),"rounds":list(self.rounds.values()),
            "history_limit":RECENT_LEARNING_ROUND_LIMIT,"round_counts":dict(self.round_counts),
            "active_round":self.active_round,"latest_publication":self.publication,
            "estimator_queries_by_version":dict(self.queries_by_version),
            "charged_transfer_bytes":dict(self.bytes)})
