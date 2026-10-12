"""Exercise manual-step races and failures without generating experiment data."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
NODE=shutil.which('node')
pytestmark=pytest.mark.skipif(not NODE,reason='Node required for transport checks')


def evaluate(setup,expression):
    source=(ROOT/'frontend/simple-simulation.js').read_text(encoding='utf-8')
    function=source[source.index('async function advance('):source.index('async function start(')]
    script=setup+'\n'+function+'\n(async()=>console.log(JSON.stringify(await ('+expression+'))))().catch(e=>{console.error(e);process.exit(1)});'
    result=subprocess.run([NODE,'-e',script],check=True,capture_output=True,text=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize('override',[{'paused':False},{'busy':True},{'error':'transport error'},{'snapshot':None},{'snapshot':{'phase':'COMPLETE'}}])
def test_step_refuses_running_busy_failed_missing_or_completed_sessions(override):
    setup='const state='+json.dumps({'paused':True,'busy':False,'snapshot':{'phase':'RELEASE','session_id':'test'},**override})+';let calls=0;const request=async()=>{calls++;};const renderTransport=()=>{};'
    assert evaluate(setup,'(async()=>{await stepSimulationOnce();return calls;})()')==0


def test_double_activation_sends_one_request_and_keeps_paused():
    setup='''const state={paused:true,busy:false,snapshot:{phase:'RELEASE',session_id:'test'}};
let calls=0,accepted=0,body,path,resolve;
const request=async(p,b)=>{calls++;path=p;body=b;return new Promise(r=>resolve=r);};
const renderTransport=()=>{};const accept=x=>{state.snapshot=x;accepted++;};
const fail=e=>{throw e;};'''
    result=evaluate(setup,"(async()=>{const first=stepSimulationOnce();const second=stepSimulationOnce();const busyWhilePending=state.busy;resolve({phase:'RELEASE',session_id:'test',time_us:1000});await Promise.all([first,second]);return {calls,accepted,body,path,busyWhilePending,paused:state.paused,busy:state.busy};})()")
    assert result=={'calls':1,'accepted':1,'body':{'delta_us':1000},'path':'/api/research/sessions/test/step','busyWhilePending':True,'paused':True,'busy':False}


def test_request_failure_releases_busy_guard_and_does_not_accept_a_snapshot():
    setup='''const state={paused:true,busy:false,snapshot:{phase:'RELEASE',session_id:'test',time_us:42}};
let accepted=0;const request=async()=>{throw Error('unavailable');};
const renderTransport=()=>{};const accept=()=>accepted++;
const fail=e=>{state.error=e.message;state.paused=true;};'''
    result=evaluate(setup,'(async()=>{await stepSimulationOnce();return {accepted,...state};})()')
    assert result['accepted']==0 and not result['busy'] and result['paused']
    assert result['snapshot']['time_us']==42 and result['error']=='unavailable'
