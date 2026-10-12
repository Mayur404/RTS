"""Exercise real models and independently replay neural/FL evidence across policies."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import torch
from rts_predictive.api.research import PairedResearchSession
from rts_predictive.artifacts.code_provenance import code_provenance
from rts_predictive.domain.research import default_research_config
from rts_predictive.federated.model import load_federated_model
from rts_predictive.gnn.calibration import TemperatureCalibrator
from scripts.audit_research_trace import audit_manifest


def replay_models(engine):
    """Recompute recorded tensors/gradients, rather than invoke runtime adapters."""
    if not engine.models:return {'neural_forwards':0,'federated_publications':0,'remote_estimates':0}
    gnn=engine.models.gnn
    remote=load_federated_model()
    private={};frozen={};updates={};delivered=set();transfers={};round_id=None
    neural=0;publications=0;estimates=0;published_us=0
    for e in engine.events:
        p=e['payload'];kind=e['event_type'];host=e['device_id']
        if kind=='PREDICTION':
            graph=p['graph'];x=torch.tensor(graph['features'],dtype=torch.float32)
            edges=torch.tensor(graph['edge_index'],dtype=torch.long)
            with torch.no_grad():risk,ttv,cause=gnn(x,edges)
            assert gnn._calibrate_probability(float(risk[0,0]))==p['miss_probability']
            assert max(0,int(float(ttv[0,0])*1_000_000))==p['ttv_us']
            assert gnn.CAUSE_NAMES[int(torch.argmax(cause[0]))]==p['cause']
            neural+=1
        elif kind=='DECISION':
            for candidate in p.get('candidates',[]):
                evidence=candidate.get('estimator_evidence')
                if not evidence:continue  # Historical traces and declared test fixtures.
                assert evidence['schema_version']=='remote-estimate-evidence/1.0'
                x=torch.tensor([evidence['features']],dtype=torch.float32)
                assert x.shape==(1,6) and bool(torch.isfinite(x).all())
                with torch.no_grad():execution,probability=remote(x)
                raw=float(probability[0,0]);temperature=remote.reliability_temperature if publications==0 else 1.0
                predicted=TemperatureCalibrator(temperature).apply(raw) if publications==0 else raw
                assert evidence['execution_mean_ms']==float(execution[0,0])
                assert evidence['execution_bound_us']==max(1,int(float(execution[0,0])*1000*remote.q95_multiplier))
                assert evidence['raw_execution_reliability']==raw
                assert evidence['execution_reliability']==predicted==candidate['predicted_execution_reliability']
                assert evidence['reliability_temperature']==temperature
                assert candidate['predicted_reliability']==predicted*candidate['analytical_delivery_reliability']
                digest=hashlib.sha256(b''.join(v.numpy().tobytes() for _,v in sorted(remote.state_dict().items()))).hexdigest()
                assert evidence['weights_sha256']==digest
                assert evidence['model_version']==candidate['estimator_version']==publications
                assert evidence['at_us']==e['timestamp_us'] and evidence['model_age_us']==e['timestamp_us']-published_us
                estimates+=1
        elif kind=='PRIVATE_OBSERVATION':
            private.setdefault(host,[]).append((p['features'],p['service_time_us']/1000,
                                                float(p['execution_on_time']),float(not p.get('latency_censored',False))))
            del private[host][:-32]
        elif kind=='FL_ROUND_START':
            round_id=p['round'];updates={};delivered=set();transfers={};frozen={}
        elif kind=='FL_TRAIN_START':
            frozen[host]=deepcopy(private[host])
            assert len(frozen[host])==p['samples']
        elif kind=='FL_TRAIN_END':
            records=frozen[host];local=deepcopy(remote);local.train()
            x=torch.tensor([r[0] for r in records]);y=torch.tensor([[r[1]] for r in records])
            rel=torch.tensor([[r[2]] for r in records]);observed=torch.tensor([[r[3]] for r in records])
            optimizer=torch.optim.SGD(local.parameters(),lr=.001);optimizer.zero_grad()
            pred,prob=local(x)
            latency=(torch.nn.functional.huber_loss(pred,y,reduction='none')*observed).sum()/observed.sum().clamp(min=1)
            loss=.1*latency+torch.nn.functional.binary_cross_entropy(prob,rel)
            assert float(loss.detach())==p['loss']
            loss.backward();optimizer.step()
            updates[host]={'samples':len(records),'weights':{k:v.detach().clone() for k,v in local.state_dict().items()}}
        elif kind=='FL_LOCAL_UPDATE':delivered.add(host)
        elif kind=='TX_START' and p['phase']=='fl_upload':transfers[p['transfer']]=host
        elif kind=='TX_END' and p['phase']=='fl_upload':delivered.add(transfers[p['transfer']])
        elif kind=='FL_AGGREGATE':
            assert p['round']==round_id and p['participants']==len(delivered)
            assert p['samples']==sum(updates[h]['samples'] for h in delivered)
        elif kind=='MODEL_PUBLISH':
            # Preserve actual arrival order; floating aggregation is order sensitive.
            participating=[u for h,u in updates.items() if h in delivered]
            # Upload arrival order can differ from local training completion order.
            arrival=[]
            for prior in engine.events:
                if prior['sequence']>=e['sequence']:break
                if prior['event_type']=='FL_ROUND_START' and prior['payload']['round']==round_id:arrival=[]
                elif prior['event_type']=='FL_LOCAL_UPDATE' and prior['payload']['round']==round_id:arrival.append(prior['device_id'])
                elif prior['event_type']=='TX_END' and prior['payload']['phase']=='fl_upload' and prior['payload']['transfer'] in transfers:
                    arrival.append(transfers[prior['payload']['transfer']])
            participating=[updates[h] for h in arrival]
            total=sum(u['samples'] for u in participating)
            weights={k:sum((u['weights'][k]*(u['samples']/total) for u in participating),torch.zeros_like(participating[0]['weights'][k]))
                     for k in participating[0]['weights']}
            digest=hashlib.sha256(b''.join(v.numpy().tobytes() for _,v in sorted(weights.items()))).hexdigest()
            assert digest==p['weights_sha256']
            assert p['samples']==total
            remote.load_state_dict(weights);remote.eval();remote.reliability_temperature=1.0
            publications+=1;published_us=e['timestamp_us']
            assert p['version']==publications
    assert all(torch.equal(value,engine.models.remote.state_dict()[key]) for key,value in remote.state_dict().items())
    return {'neural_forwards':neural,'federated_publications':publications,'remote_estimates':estimates}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='.validation/end-to-end-audit')
    args=parser.parse_args();root=Path(args.output)
    if (root/'report.json').exists():parser.error('use a fresh output directory to preserve prior evidence')
    root.mkdir(parents=True,exist_ok=True);cases=[];totals=Counter()
    source=code_provenance()
    families=('nominal','bursty','thermal','unreliable')
    matrix=[(f,s,'edf',None) for f in families for s in (1000,1001,1002)]
    matrix += [(f,1000,p,None) for f in families for p in ('fifo','rm','always_offload','reactive','predictive_no_fallback')]
    matrix += [(f,1000,'edf',flag) for f in families for flag in ('watchdog','fl','offload','fallback')]
    for family,seed,baseline,disabled in matrix:
        session=PairedResearchSession(default_research_config(seed,family),root/'runs',baseline=baseline,
                                      **({'enable_'+disabled:False} if disabled else {}))
        assert session.source['source_sha256']==source['source_sha256'], 'source changed during audit'
        snapshot=session.step(session.config.end_us);checks={};replays={}
        a,b=session.engines.values()
        assert {tid:t.demand for tid,t in a.tasks.items()}=={tid:t.demand for tid,t in b.tasks.items()}
        for policy,engine in session.engines.items():
            checks[policy]=audit_manifest(session.root/policy/'manifest.json')
            replays[policy]=replay_models(engine)
            totals['canonical_events']+=checks[policy]['canonical_events']
            totals['policy_traces']+=1;totals.update(replays[policy])
        protected=session.engines['protected'];counts=Counter(e['event_type'] for e in protected.events)
        absent={'watchdog':('WATCHDOG_CHECK','WATCHDOG_ABORT'),'fl':('FL_TRAIN_START','FL_AGGREGATE','MODEL_PUBLISH'),
                'offload':('OFFLOAD_DISPATCH',),'fallback':('EARLY_EXIT','FALLBACK_ADMITTED')}
        if disabled:assert all(counts[k]==0 for k in absent[disabled])
        totals['offloads']+=counts['OFFLOAD_DISPATCH'];totals['watchdog_aborts']+=counts['WATCHDOG_ABORT']
        totals['early_exits']+=counts['EARLY_EXIT'];totals['fallback_checks']+=counts['FALLBACK_BOUND_CHECK']
        cases.append({'family':family,'seed':seed,'baseline':baseline,'disabled_feature':disabled,
                      'pair_id':session.id,'comparison':snapshot['comparison'],'audits':checks,'model_replay':replays})
        print(f"PASS {len(cases)}/{len(matrix)}: {family}, seed {seed}, {baseline}, disable={disabled}",flush=True)
    assert all(totals[k]>0 for k in ('neural_forwards','federated_publications','offloads','watchdog_aborts','early_exits','fallback_checks'))
    assert code_provenance()['source_sha256']==source['source_sha256'], 'source changed during audit'
    report={'status':'PASS','evidence':'SIMULATED_IMPLEMENTATION_CHECK','source':source,'cases':cases,'totals':dict(totals),
            'scope':'three EDF paired seeds per family; one seed per other comparator/ablation; not a publication-scale result'}
    (root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report['totals']),flush=True)


if __name__=='__main__':main()
