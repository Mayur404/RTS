"""Long-horizon and fleet-size checks with real models and preserved raw evidence."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from rts_predictive.api.research import PairedResearchSession
from rts_predictive.api.scenario_designer import ScenarioInput, template
from rts_predictive.artifacts.code_provenance import code_provenance
from rts_predictive.domain.research import default_research_config
from scripts.audit_research_trace import audit_manifest
from scripts.verify_runtime_end_to_end import replay_models


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='.validation/deep-review-20261011/learning-stress')
    parser.add_argument('--case',choices=['long-nominal','long-bursty','eight-devices'])
    args=parser.parse_args();root=Path(args.output)
    if root.exists():parser.error('use a fresh output directory')
    root.mkdir(parents=True);source=code_provenance();cases=[]
    configs=[('long-nominal',default_research_config(1100,'nominal',5_000_000),False),
             ('long-bursty',default_research_config(1101,'bursty',5_000_000),False)]
    data=template('nominal');data['seed']=1102;data['release_end_us']=2_000_000
    for index in range(4):
        device=deepcopy(data['devices'][index]);device['device_id']='Device_'+str(index+5)
        device['name']=device['name']+' 2';data['devices'].append(device)
    for workflow in data['workflows']:workflow['period_us']*=2
    config,_=ScenarioInput.model_validate(data).compile();configs.append(('eight-devices',config,True))
    for name,config,custom in configs:
        if args.case and name!=args.case:continue
        assert source==code_provenance(),'source changed during stress check'
        session=PairedResearchSession(config,root/'runs',custom_scenario=custom)
        snapshot=session.step(config.end_us)
        checks={policy:audit_manifest(session.root/policy/'manifest.json') for policy in session.engines}
        replays={policy:replay_models(engine) for policy,engine in session.engines.items()}
        learning=snapshot['after']['learning'];models=session.engines['protected'].models
        assert learning['gnn']['successful']>0 and learning['round_counts'].get('published',0)>0
        assert learning['latest_publication']['version']==models.version
        assert len(learning['rounds'])<=learning['history_limit']
        assert snapshot['after']['metrics']['pending_jobs']==0
        if name=='long-bursty':
            assert any(int(version)>0 and count>0 for version,count in learning['estimator_queries_by_version'].items())
        if name=='long-nominal':assert learning['round_counts']['published']>learning['history_limit']
        row={'name':name,'pair_id':session.id,'configuration_hash':config.config_hash,'devices':len(config.devices),
             'release_end_us':config.release_end_us,'learning':learning,'audits':checks,'model_replay':replays}
        cases.append(row);(root/(name+'.json')).write_text(json.dumps(row,indent=2),encoding='utf-8')
        print('PASS '+name+' / published '+str(models.version),flush=True)
    report={'status':'PASS','evidence':'SIMULATED_IMPLEMENTATION_CHECK','source':source,'cases':cases,
            'scope':'selected diagnostic paired configurations; not a statistical comparison or calibration study'}
    (root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':main()
