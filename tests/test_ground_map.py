"""Presentation geometry, resource evidence and protection-record invariants."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]
NODE=shutil.which('node')
SOURCE=(ROOT/'frontend/ground-map.js').read_text(encoding='utf-8')
pytestmark=pytest.mark.skipif(not NODE,reason='Node required')


def js(start,end,expression,setup=''):
    function=SOURCE[SOURCE.index(start):SOURCE.index(end,SOURCE.index(start))] if end else SOURCE[SOURCE.index(start):]
    helpers=(ROOT/'frontend/facility-scene.js').read_text(encoding='utf-8')
    out=subprocess.run([NODE,'-e',helpers+setup+function+'\nconsole.log(JSON.stringify('+expression+'));'],check=True,capture_output=True,text=True)
    return json.loads(out.stdout)


@pytest.mark.parametrize('count',[2,4,6,8])
def test_ground_positions_are_unique_and_fit_every_device(count):
    devices=[{'device_id':f'D{i}'} for i in range(count)]
    positions=js('function groundPositions','\nfunction resourceUsage',f'groundPositions({json.dumps(devices)})')
    assert len(positions)==count
    assert len({(p['x'],p['y']) for p in positions.values()})==count
    assert all(94<=p['x']<=1106 and 45<=p['y']<=602 for p in positions.values())


def test_usage_comes_from_recorded_ppm_and_preserves_sample_time():
    result=js('function resourceUsage','\nfunction groundRoute','resourceUsage({at_us:42,cpu_ppm:750000,gpu_ppm:200000})')
    assert result=={'known':True,'cpu':75,'gpu':20,'at_us':42}
    assert js('function resourceUsage','\nfunction groundRoute','resourceUsage({cpu_ppm:1000000})')['cpu'] is None


def test_route_starts_and_ends_at_directional_device_ports():
    out=js('function groundRoute','\nfunction protectionRecord','(()=>{const r=groundRoute({x:0,y:0},{x:200,y:0});return [r.point(0),r.point(1),r.point(.5)]})()')
    assert out==[[37,0],[156,0],[96.5,0]]


def test_watchdog_timeline_requires_exact_task_event_records():
    events=[{'event_type':k,'timestamp_us':i*100,'task_id':'t','payload':{}} for i,k in enumerate(['OFFLOAD_DISPATCH','WATCHDOG_ABORT','FALLBACK_ADMITTED','EARLY_EXIT','TASK_COMMIT'],1)]
    x={'after':{'tasks':[{'id':'t','commit_us':500,'degraded':True}],'handoffs':[{'task':'t','events':events}],'events':[]}}
    out=js('function protectionRecord','\nfunction buildGroundMap',f'protectionRecord({json.dumps(x)})')
    assert [v[2] for v in out['steps']]==[100,200,300,400,500]
    # A degraded flag alone cannot manufacture an early-exit timestamp.
    x['after']['handoffs'][0]['events']=[e for e in events if e['event_type']!='EARLY_EXIT']
    out=js('function protectionRecord','\nfunction buildGroundMap',f'protectionRecord({json.dumps(x)})')
    assert next(s[2] for s in out['steps'] if s[0]=='EARLY_EXIT') is None


def test_archived_local_exit_uses_recorded_event_not_another_task():
    x={'after':{'tasks':[{'id':'t','degraded':True,'fallback_admitted':{'at_us':90},'diagnostics':{}}],'handoffs':[],'events':[{'task_id':'other','event_type':'EARLY_EXIT','timestamp_us':1}]}}
    archive=[{'task_id':'t','event_type':'EARLY_EXIT','timestamp_us':95}]
    out=js('function protectionRecord','\nfunction buildGroundMap',f'protectionRecord({json.dumps(x)},"t",{json.dumps(archive)})')
    assert next(s[2] for s in out['steps'] if s[0]=='EARLY_EXIT')==95


@pytest.mark.parametrize('status',['QUEUED','RUNNING','COMMITTED','MISSED','SKIPPED'])
def test_recovery_arrow_exists_only_while_fallback_task_is_active(status):
    x={'phase':'RELEASE','after':{'tasks':[{'id':'t','state':status,'fallback_admitted':{'at_us':20}}],
       'handoffs':[{'task':'t','events':[{'event_type':'WATCHDOG_ABORT','timestamp_us':20,'task_id':'t','payload':{}}]}],'events':[]}}
    out=js('function protectionRecord','\nfunction buildGroundMap',f'liveRecoveryRecord({json.dumps(x)})')
    assert (out is not None)==(status in ['QUEUED','RUNNING'])
    x['phase']='COMPLETE'
    assert js('function protectionRecord','\nfunction buildGroundMap',f'liveRecoveryRecord({json.dumps(x)})') is None


def test_historical_selection_does_not_draw_another_tasks_recovery():
    x={'phase':'RELEASE','after':{'tasks':[{'id':'old','state':'COMMITTED','fallback_admitted':{'at_us':20}},
       {'id':'active','state':'RUNNING','fallback_admitted':{'at_us':30}}],
       'handoffs':[{'task':id,'events':[{'event_type':'WATCHDOG_ABORT','timestamp_us':at,'task_id':id,'payload':{}}]}
                   for id,at in [('active',30),('old',20)]],'events':[]}}
    out=js('function protectionRecord','\nfunction buildGroundMap',f'liveRecoveryRecord({json.dumps(x)})')
    assert out['task']['id']=='active'
    assert js('function protectionRecord','\nfunction buildGroundMap',f'liveRecoveryRecord({json.dumps(x)},"old")') is None
    history=js('function protectionRecord','\nfunction buildGroundMap',f'protectionRecord({json.dumps(x)},"old")')
    assert history['abort']['timestamp_us']==20


def test_scenario_variations_preserve_template_and_filter_removed_devices():
    template={'devices':[{'device_id':'Device_1','name':'Drone','kind':'drone','cpu_speed_ppm':1000000},{'device_id':'Device_2','name':'Server','kind':'server','cpu_speed_ppm':2000000},{'device_id':'Device_3','name':'Rover','kind':'rover'},{'device_id':'Device_4','name':'Arm','kind':'arm'}],'workflows':[{'pipeline_id':'autonomy','period_us':90000},{'pipeline_id':'control','period_us':20000}],'faults':[{'device_id':'Device_4'},{'device_id':'Device_2'}]}
    out=js('function configureGroundScenario',None,'(()=>{const next=configureGroundScenario(t,2,"control",150);return {original:t,next}})()',setup='const t='+json.dumps(template)+';')
    assert out['original']==template
    assert len(out['next']['devices'])==2
    assert out['next']['faults']==[{'device_id':'Device_2'}]
    assert out['next']['workflows']==[{'pipeline_id':'control','period_us':13333}]


@pytest.mark.parametrize('count',[2,8])
@pytest.mark.parametrize('mix',['mixed','autonomy','control','telemetry'])
@pytest.mark.parametrize('rate',[50,150])
def test_exposed_fleet_and_task_controls_compile_existing_scenario_contract(count,mix,rate):
    from rts_predictive.api.scenario_designer import template,ScenarioInput
    original=template('unreliable')
    scenario=js('function configureGroundScenario',None,f'configureGroundScenario(t,{count},{json.dumps(mix)},{rate})',setup='const t='+json.dumps(original)+';')
    config,estimate=ScenarioInput.model_validate(scenario).compile()
    assert len(config.devices)==count
    assert estimate['released_tasks']<=6000
    assert len(config.workflows)==(3 if mix=='mixed' else 1)


def test_recovery_stress_is_explicit_configured_fault_input():
    from rts_predictive.api.scenario_designer import template,ScenarioInput
    original=template('unreliable')
    scenario=js('function configureGroundScenario',None,'configureGroundScenario(t,6,"mixed",100,true)',setup='const t='+json.dumps(original)+';')
    config,_=ScenarioInput.model_validate(scenario).compile()
    peer_faults=[f for f in config.faults if f.device_id!='Device_1']
    assert len(peer_faults)==5
    assert all(f.start_us==98000 and f.end_us==300000 and f.gpu_ppm==950000 for f in peer_faults)
