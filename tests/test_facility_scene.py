"""Illustrative movement and canonical task-owner evidence stay separate."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]
NODE=shutil.which('node')
SOURCE=(ROOT/'frontend/facility-scene.js').read_text(encoding='utf-8')
pytestmark=pytest.mark.skipif(not NODE,reason='Node required')


def js(expression):
    out=subprocess.run([NODE,'-e',SOURCE+'\nconsole.log(JSON.stringify('+expression+'));'],capture_output=True,text=True,check=True)
    return json.loads(out.stdout)


@pytest.mark.parametrize('kind',['drone','rover'])
def test_mobile_paths_move_and_close_without_altering_time_or_device(kind):
    out=js('(()=>{const d={device_id:"D",kind:'+json.dumps(kind)+'};return {d,start:facilityDevicePosition(d,0,0),later:facilityDevicePosition(d,0,150000),loop:facilityDevicePosition(d,0,900000)}})()')
    assert out['d']=={'device_id':'D','kind':kind}
    assert out['start']==out['loop']
    assert out['start']!=out['later']


def test_rovers_follow_service_road_and_drones_stay_inside_patrol_area():
    for kind in ['rover','drone']:
        points=js(f'Array.from({{length:101}},(_,i)=>facilityDevicePosition({{kind:"{kind}"}},0,i*9000))')
        for p in points:
            assert 100<=p['x']<=1100 and 250<=p['y']<=590
            if kind=='rover':assert p['x'] in (140,1060) or p['y'] in (275,565)


@pytest.mark.parametrize('kind',['server','arm','station','chip'])
def test_fixed_equipment_has_no_travel_path(kind):
    assert js(f'facilityDevicePosition({{kind:"{kind}"}},0,100000)') is None


def test_active_tasks_resolve_exact_sample_owners_and_remote_origins():
    x={'after':{'resources':{'peer':{'at_us':12,'cpu_slot':'op-1','gpu_slot':'a-1','operations':[{'id':'op-1','task':'decision-task','kind':'decision'}]}},'attempts':[{'id':'a-1','task':'remote-task'}],'tasks':[{'id':'decision-task','name':'ServoControl','device':'peer'},{'id':'remote-task','name':'Perception','device':'origin'}]}}
    out=js(f'activeDeviceTasks({json.dumps(x)},"peer")')
    assert out[0]['task']=='decision-task' and out[0]['operation']=='decision'
    assert out[1]['task']=='remote-task' and out[1]['origin']=='origin'


def test_unknown_resource_sample_never_manufactures_task_owners():
    x={'after':{'resources':{},'attempts':[],'tasks':[]}}
    assert js(f'activeDeviceTasks({json.dumps(x)},"missing")')==[]


def test_idle_reservations_and_background_are_distinguished():
    x={'after':{'resources':{'d':{'at_us':0,'cpu_slot':None,'gpu_slot':None,'gpu_cpu_reservation_ppm':200000,'background_gpu_ppm':500000}},'attempts':[],'tasks':[]}}
    out=js(f'activeDeviceTasks({json.dumps(x)},"d")')
    assert [o['label'] for o in out]==['GPU reservation','Background load']


def test_facility_background_has_service_loop_and_no_hexagonal_ground():
    svg=js('facilitySceneSvg()')
    assert 'FACILITY SERVICE LOOP' in svg and 'EDGE COMPUTE HUB' in svg
    assert 'hex' not in svg.lower() and '<polygon' not in svg


def test_device_callouts_avoid_each_other_for_the_initial_facility():
    devices=[{'device_id':str(i),'kind':kind} for i,kind in enumerate(['drone','server','rover','arm','rover','arm'])]
    out=js('(()=>{const d='+json.dumps(devices)+';const p=facilityPositions(d);return {p,labels:facilityLabelLayout(p,d,"0")};})()')
    boxes=[]
    for id,offset in out['labels'].items():
        p=out['p'][id];box=(p['x']+offset['x'],p['y']+offset['y'])
        assert 38<=box[0]<=1162-188 and 30<=box[1]<=726-127
        for x,y in boxes:assert box[0]+188<=x or x+188<=box[0] or box[1]+127<=y or y+127<=box[1]
        boxes.append(box)
