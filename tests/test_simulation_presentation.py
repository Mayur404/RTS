"""Behavioral frontend checks; fixtures are never experiment evidence."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
NODE=shutil.which('node')
pytestmark=pytest.mark.skipif(not NODE,reason='Node required for frontend checks')


def evaluate(expression):
    source=(ROOT/'frontend/task-state.js').read_text(encoding='utf-8')
    app=(ROOT/'frontend/simple-simulation.js').read_text(encoding='utf-8')
    source+='\n'+app[app.index('function transferFraction'):app.index('async function request')]
    result=subprocess.run([NODE,'-e',source+'\nconsole.log(JSON.stringify('+expression+'));'],
                          check=True,capture_output=True,text=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize('status', ['MISSED','SKIPPED'])
def test_failure_color_wins_over_early_exit_mode(status):
    value=evaluate('({state:taskVisualState({state:'+json.dumps(status)+',degraded:true}),'
                   'color:taskColor({state:'+json.dumps(status)+',degraded:true})})')
    assert value['state']==status
    assert value['color']!=evaluate('taskColor({state:"COMMITTED",degraded:true})')


def test_early_exit_is_distinct_from_full_completion():
    assert evaluate('taskVisualState({state:"COMMITTED",degraded:true})')=='DEGRADED'
    assert evaluate('taskVisualState({state:"COMMITTED",degraded:false})')=='COMMITTED'


@pytest.mark.parametrize('layer', [0,1,3,4])
def test_gpu_progress_depends_on_delivered_service_not_layer_ordinal(layer):
    assert evaluate('gpuLayerProgress({total_work_us:11,work_done_us:4,layer:'+str(layer)+'})')==[1,1/3,0,0]


def test_shorter_fallback_never_implies_full_gpu_layers():
    assert evaluate('gpuLayerProgress({total_work_us:11,work_done_us:11,degraded:true})')==[0,0,0,0]
    assert evaluate('gpuLayerProgress({total_work_us:11,work_done_us:11})')==[1,1,1,1]
    assert evaluate('gpuLayerProgress(null)')==[0,0,0,0]


@pytest.mark.parametrize('at,fraction', [(9,0),(10,0),(89,0),(90,0),(140,.5),(190,1)])
def test_packet_position_respects_radio_serialization(at,fraction):
    value=evaluate('transferFraction({source:"sender",phase:"request",bytes:100,start_us:10,end_us:190},'
                   '{time_us:'+str(at)+',devices:[{device_id:"sender",bandwidth_mbps:10}]})')
    assert value==fraction


def test_zero_byte_cancel_still_occupies_one_microsecond():
    expression='transferFraction({source:"sender",phase:"cancel",bytes:0,start_us:0,end_us:101},'
    assert evaluate(expression+'{time_us:0,devices:[{device_id:"sender",bandwidth_mbps:10}]})')==0
    assert evaluate(expression+'{time_us:51,devices:[{device_id:"sender",bandwidth_mbps:10}]})')==.5
