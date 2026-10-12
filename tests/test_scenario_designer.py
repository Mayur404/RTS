"""Authoring validation, actual scheduling, baseline routing and evidence bindings."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from rts_predictive.api.scenario_designer import ScenarioInput, template
from rts_predictive.simulator.research_engine import ResearchEngine
from rts_predictive.dashboard.research_projection import ResearchProjection
from test_research_api import ASGIClient


@pytest.mark.parametrize('family',['nominal','bursty','thermal','unreliable'])
def test_templates_compile_and_dependency_counts_match_actual_releases(family):
    data=template(family);data['release_end_us']=100000
    config,counts=ScenarioInput.model_validate(data).compile()
    engine=ResearchEngine(config,'edf');engine.run_until(config.end_us)
    projection=ResearchProjection()
    for event in engine.events:projection.consume(event)
    metrics=projection.metrics()
    assert metrics['released_jobs']==counts['released_jobs']
    assert len(engine.tasks)==counts['released_tasks']
    assert metrics['pending_jobs']==0
    commits={e['task_id']:e for e in engine.events if e['event_type']=='TASK_COMMIT'}
    for event in engine.events:
        if event['event_type']=='TASK_READY':
            for parent in engine.tasks[event['task_id']].parents:
                assert parent in commits and commits[parent]['sequence']<event['sequence']


def bad_cycle(d):d['workflows'][0]['dependency_edges'].append(['Tracking','Sense'])
def bad_drain(d):d['drain_us']=1
def bad_duplicate(d):d['devices'].append(deepcopy(d['devices'][0]))
def bad_work(d):d['workflows'][0]['tasks'][0]['bcet_us']=999999
def bad_fault(d):d['faults']=[dict(device_id='unknown',start_us=0,end_us=10)]
def bad_count(d):d['release_end_us']=5000000;d['workflows'][0]['period_us']=10000
def bad_constant(d):d['workflows'][0]['tasks'][0]['distribution']='constant'
def bad_exit(d):d['workflows'][0]['tasks'][2]['exit_points'][0]['elapsed_work_interval_us']=[0,999999]


@pytest.mark.parametrize('mutate',[bad_cycle,bad_drain,bad_duplicate,bad_work,bad_fault,bad_count,bad_constant,bad_exit])
def test_invalid_scenarios_are_rejected_before_creating_a_session(mutate):
    data=template('nominal');mutate(data)
    from rts_predictive.api.research import SESSIONS
    existing=set(SESSIONS)
    with ASGIClient() as client:
        response=client.post('/api/research/scenarios/validate',json=data)
        assert response.status_code==422
        response=client.post('/api/research/sessions',json={'scenario':data})
        assert response.status_code==422
    assert set(SESSIONS)==existing


@pytest.mark.parametrize('change',[{'seed':True},{'base_link_us':1.5},{'unknown_setting':1},{'layer_count':3}])
def test_unsupported_or_noninteger_settings_are_visible_errors(change):
    data=template('nominal');data.update(change)
    with pytest.raises(ValidationError):ScenarioInput.model_validate(data)


def test_custom_fork_join_on_named_robot_and_non_edf_artifacts(tmp_path,monkeypatch):
    import rts_predictive.api.research as api
    original=api.PairedResearchSession
    monkeypatch.setattr(api,'PairedResearchSession',lambda config,**kwargs:original(config,output_root=tmp_path/'.validation'/'research-sessions',**kwargs))
    data=template('nominal');data['release_end_us']=100000
    data['devices']=data['devices'][:1];data['devices'][0].update(device_id='Robot_A',name='Shared assembly robot',kind='arm')
    data['workflows']=data['workflows'][:1];data['workflows'][0]['pipeline_id']='assembly'
    with ASGIClient() as client:
        valid=client.post('/api/research/scenarios/validate',json=data).json()
        assert valid['valid']
        response=client.post('/api/research/sessions',json={'scenario':data,'baseline':'rm'})
        assert response.status_code==201
        monkeypatch.setattr(api,'ROOT',tmp_path)
        snap=response.json();uid=snap['session_id'];base='/api/research/sessions/'+uid
        assert snap['baseline']=='rm'
        assert snap['config_hash']==valid['configuration_hash']
        assert snap['models']['validation_scope']=='custom_scenario_unvalidated'
        assert snap['devices'][0]['device_id']=='Robot_A'
        while snap['phase']!='COMPLETE':snap=client.post(base+'/step',json={'delta_us':100000}).json()
        assert snap['before']['metrics']['pending_jobs']==snap['after']['metrics']['pending_jobs']==0
        for policy in ('rm','protected'):
            manifest=client.get(base+'/artifacts/'+policy+'/manifest.json').json()
            assert manifest['configuration_hash']==valid['configuration_hash']
            assert client.get(base+'/artifacts/'+policy+'/events.jsonl').status_code==200
        assert client.get(base+'/artifacts/fifo/metrics.json').status_code==404
        stored=client.get(base+'/evidence/config.json').json()
        assert stored['devices'][0]['device_id']=='Robot_A'
        assert stored['workflows'][0]['dependency_edges']==[list(edge) for edge in data['workflows'][0]['dependency_edges']]
        assert client.delete(base).status_code==204
