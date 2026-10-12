"""Behavioral checks for the current two-view presentation and transport."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
SOURCE = (ROOT / 'frontend/simple-simulation.js').read_text(encoding='utf-8')
pytestmark = pytest.mark.skipif(not NODE, reason='Node required')


def js(setup, start, end, expression, layout=False):
    function = SOURCE[SOURCE.index(start):SOURCE.index(end, SOURCE.index(start))]
    helper = (ROOT / 'frontend/graph-layout.js').read_text(encoding='utf-8') if layout else ''
    result = subprocess.run([NODE, '-e', helper + setup + '\n' + function + '\n(async()=>console.log(JSON.stringify(await (' + expression + '))))().catch(e=>{console.error(e);process.exit(1)});'], capture_output=True, text=True, encoding='utf-8', check=True)
    return json.loads(result.stdout)


def test_live_connections_exclude_queued_and_finished_transfers():
    x = {'time_us': 10, 'after': {'transfers': [{'start_us': 11, 'end_us': 20}, {'start_us': 0, 'end_us': 10}, {'start_us': 10, 'end_us': 20}]}}
    assert js('', 'function liveTransfers', '\nfunction transferFraction', f'liveTransfers({json.dumps(x)})') == [{'start_us': 10, 'end_us': 20}]


def test_packets_wait_at_sender_until_serialization_finishes():
    setup = 'const t={source:"D",start_us:0,end_us:100,bytes:100};const x={devices:[{device_id:"D",bandwidth_mbps:10}],time_us:50};'
    assert js(setup, 'function transferFraction', '\nasync function request', '[transferFraction(t,x),transferFraction(t,{...x,time_us:90}),transferFraction(t,{...x,time_us:200})]') == [0, .5, 1]


@pytest.mark.parametrize('status',['RUNNING','QUEUED','COMMITTED','MISSED','SKIPPED'])
def test_task_labels_preserve_terminal_outcome_and_clear_active_host_arrow(status):
    task={'state':status,'degraded':True,'host':'Device_2'}
    labels={'RUNNING':'Running','QUEUED':'Queued','COMMITTED':'Committed','MISSED':'Missed','SKIPPED':'Skipped'}
    out=js('const statusNames='+json.dumps(labels)+';', 'function taskStatusLabel', '\nfunction renderBoard',
           f'[taskStatusLabel({json.dumps(task)}),taskHostLabel({json.dumps(task)},"Device_1")]')
    assert out[0]==labels[status]+' · early exit'
    assert out[1]==(' → D2' if status in ['RUNNING','QUEUED'] else '')


def test_paired_categories_include_regressions_and_unresolved_jobs():
    statuses = [('COMPLETE','COMPLETE'), ('MISSED','COMPLETE'), ('COMPLETE','MISSED'), ('MISSED','MISSED'), ('ACTIVE','COMPLETE')]
    x = {side: {'jobs': [{'id':str(i),'status':s[index]} for i,s in enumerate(statuses)]} for index,side in enumerate(['before','after'])}
    assert js('', 'function pairedJobCounts', '\nfunction liveTransfers', f'pairedJobCounts({json.dumps(x)})') == {'both_met':1,'rescued':1,'regressed':1,'both_missed':1,'pending':1}


@pytest.mark.parametrize('override', [{'busy':True}, {'error':'offline'}, {'snapshot':None}, {'snapshot':{'phase':'COMPLETE'}}])
def test_transport_refuses_invalid_steps(override):
    setup = 'const state='+json.dumps({'busy':False,'error':None,'snapshot':{'session_id':'s','phase':'RELEASE'},**override})+';let calls=0;const renderTransport=()=>{};const request=async()=>{calls++;};'
    assert js(setup, 'async function advance', '\nasync function stepSimulationOnce', '(async()=>{await advance(1000);return calls;})()') == 0


def test_only_one_request_in_flight_and_failed_requests_keep_last_snapshot():
    setup = '''const state={busy:false,error:null,snapshot:{session_id:'s',phase:'RELEASE',time_us:10}};
let calls=0,reject;const renderTransport=()=>{};const request=()=>{calls++;return new Promise((r,j)=>reject=j)};
const accept=()=>{throw Error('must not accept failed result')};const fail=e=>{state.error=e.message;state.paused=true};'''
    out = js(setup, 'async function advance', '\nasync function stepSimulationOnce', "(async()=>{const first=advance(1000);await advance(1000);reject(Error('offline'));await first;return {calls,...state};})()")
    assert out['calls']==1 and not out['busy'] and out['paused']
    assert out['error']=='offline' and out['snapshot']['time_us']==10


def test_pending_setting_change_starts_new_run_only_after_step_finishes():
    setup='''const state={busy:false,error:null,pendingRestart:true,snapshot:{session_id:'s',phase:'RELEASE'}};
let resolve,restarts=0,busyAtRestart;const renderTransport=()=>{};const request=()=>new Promise(r=>resolve=r);
const accept=()=>{};const fail=e=>{throw e};const start=()=>{restarts++;busyAtRestart=state.busy};'''
    out=js(setup,'async function advance','\nasync function stepSimulationOnce','(async()=>{const pending=advance(1000);const before=restarts;resolve({});await pending;return {before,restarts,busyAtRestart,pendingRestart:state.pendingRestart};})()')
    assert out=={'before':0,'restarts':1,'busyAtRestart':False,'pendingRestart':False}
