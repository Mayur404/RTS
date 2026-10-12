"use strict";
// Presentation only: all task states, transfers and results come from session snapshots.
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state={snapshot:null,paused:false,busy:false,starting:true,error:null,workflow:'autonomy',view:'simulation',history:[],selectedTask:null,device:'Device_1',protectionTask:null,protectionEvents:[],zoom:1};
window.researchState=state;
const colors=['#6366f1','#0ea5a4','#f59e0b','#ec4899','#3b82f6','#a855f7','#84a70c','#f97316'];
const statusColors={BLOCKED:'#94a3b8',DECIDING:'#d97706',QUEUED:'#d97706',RUNNING:'#2563eb',OFFLOADED:'#8b5cf6',COMMITTED:'#059669',DEGRADED:'#ea580c',MISSED:'#dc2626',SKIPPED:'#94a3b8'};
const statusNames={BLOCKED:'Waiting',DECIDING:'Deciding',QUEUED:'Queued',RUNNING:'Running',OFFLOADED:'Offloaded',COMMITTED:'Committed',DEGRADED:'Early exit',MISSED:'Missed',SKIPPED:'Skipped'};
const ms=n=>n==null?'—':(n/1000).toFixed(1)+' ms';
let lastFrame=0,previousPackets=new Map(),acceptedAt=0,packetDuration=34;

function pairedJobCounts(x){
  const before=new Map(x.before.jobs.map(j=>[j.id,j]));
  const counts={both_met:0,rescued:0,regressed:0,both_missed:0,pending:0};
  for(const j of x.after.jobs){const b=before.get(j.id);if(!b)continue;
    const key=b.status==='ACTIVE'||j.status==='ACTIVE'?'pending':b.status==='COMPLETE'?(j.status==='COMPLETE'?'both_met':'regressed'):(j.status==='COMPLETE'?'rescued':'both_missed');counts[key]++;}
  return counts;
}

function liveTransfers(x){return x.after.transfers.filter(t=>t.start_us<=x.time_us&&x.time_us<t.end_us);}
function transferFraction(t,x){
  const sender=x.devices.find(d=>d.device_id===t.source);
  if(!sender)return 0;
  const serialized=t.start_us+Math.max(1,Math.ceil(t.bytes*8/sender.bandwidth_mbps));
  return Math.max(0,Math.min(1,(x.time_us-serialized)/Math.max(1,t.end_us-serialized)));
}

async function request(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});if(!r.ok){let detail;try{detail=(await r.json()).detail;}catch{detail=r.statusText;}throw Error(typeof detail==='string'?detail:JSON.stringify(detail));}return r.json();}
function svgText(x,y,value,size=12,fill='#334155',weight=400){return `<text x="${x}" y="${y}" fill="${fill}" font-size="${size}" font-weight="${weight}">${esc(value)}</text>`;}
function taskName(value){return value.replace(/([a-z])([A-Z])/g,'$1 $2');}

function renderBoard(x){renderGroundMap(x);}
function renderConnections(x){renderGroundConnections(x);}

function renderInspector(x){
  const t=x?.after.tasks.find(t=>t.id===state.selectedTask);$('task-inspector').hidden=!t;if(!t)return;
  const job=x.after.jobs.find(j=>j.id===t.job),w=x.workflows.find(w=>w.pipeline_id===job?.workflow);
  const parents=w?.dependency_edges.filter(([,b])=>b===t.name).map(([a])=>a)||[];
  const a=x.after.attempts.find(a=>a.id===(t.committed_attempt||t.attempt));
  const diagnostics=t.diagnostics||{},prediction=diagnostics.prediction,decision=diagnostics.decision;
  $('task-detail').innerHTML=`<h2>${esc(taskName(t.name))} <small>· ${esc(t.device)}</small></h2><dl>${[['State',t.state+(t.degraded?' / early exit':'')],['Execution host',t.host||'Not assigned'],['Deadline',ms(t.deadline_us)],['Delivered work',a?ms(a.work_done_us)+' / '+ms(a.total_work_us):'Not started'],['Needs',parents.join(', ')||'No predecessors']].map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl><p>${esc(t.id)}</p>${prediction?`<p>Recorded prediction: ${(prediction.miss_probability*100).toFixed(1)}% task-failure risk at ${ms(prediction.at_us)}. Decision: ${esc(decision?.action||'pending')}. Predicted values are not guarantees.</p>`:''}`;
}

function renderResults(x){
  renderPlainResults(x);
  for(const [id,m]of [['before',x.before.metrics],['after',x.after.metrics]]){$(id).textContent=m.job_dmr_pct==null?'—':m.job_dmr_pct.toFixed(2)+'%';$(id+'-detail').textContent=`${m.missed_jobs} missed / ${m.released_jobs} released · ${m.pending_jobs} active`;}
  const c=x.comparison;$('change').textContent=c.change_pp==null?'—':(c.change_pp<0?'−':'')+Math.abs(c.change_pp).toFixed(2)+' pp';$('change-detail').textContent=c.change_pp<0?'Protection increased the miss rate':c.change_pp>0?'Fewer misses with protection':'No miss-rate difference';
  $('result-status').textContent=c.final?'Final results':'Provisional results';$('run-explain').textContent=c.final?'All released jobs are resolved. Miss rate = missed end-to-end jobs / released jobs.':'The run is still in progress. Active jobs remain in the denominator; results can change until the final drain.';
  const counts=pairedJobCounts(x),total=Object.values(counts).reduce((a,b)=>a+b,0),styles={both_met:['Both met','#10b981'],rescued:['Met only with protection','#3b82f6'],regressed:['Missed only with protection','#f59e0b'],both_missed:['Both missed','#ef4444'],pending:['Still active','#cbd5e1']};
  $('paired-bar').innerHTML=Object.entries(counts).filter(([,n])=>n).map(([k,n])=>`<span style="width:${n/Math.max(1,total)*100}%;background:${styles[k][1]}" title="${styles[k][0]}: ${n}"></span>`).join('');
  $('paired-counts').innerHTML=Object.entries(counts).map(([k,n])=>`<div data-paired-category="${k}" data-paired-count="${n}"><strong style="color:${styles[k][1]}">${n}</strong><span>${styles[k][0]}</span></div>`).join('');
  const h=state.history,max=Math.max(5,...h.flatMap(v=>[v.a??0,v.b??0]))*1.1;let chart='';
  for(const f of [0,.5,1]){const y=198-f*165;chart+=`<path d="M52 ${y}H975" stroke="#e2e8f0"/>${svgText(3,y+4,(f*max).toFixed(1)+'%',11,'#64748b')}`;}
  for(const [k,color]of [['a','#64748b'],['b','#059669']]){const points=h.filter(v=>v[k]!=null).map(v=>`${52+v.t/x.end_us*923},${198-v[k]/max*165}`).join(' ');chart+=`<polyline points="${points}" fill="none" stroke="${color}" stroke-width="3"/>`;}
  chart+=svgText(52,227,'0 s',11,'#64748b')+svgText(921,227,(x.end_us/1e6).toFixed(2)+' s',11,'#64748b');$('trend').innerHTML=chart;
  const m=x.after.metrics;$('extra-results').innerHTML=[['Committed tasks',m.committed_tasks],['Offload dispatches',m.offloads],['Watchdog recovery starts',m.watchdog_aborts],['Early exits',m.early_exits],['GNN inference attempts',m.gnn_inferences],['Mean output utility proxy',m.mean_utility==null?'—':m.mean_utility.toFixed(3)]].map(([k,v])=>`<div>${esc(k)}<b>${esc(v)}</b></div>`).join('');
  $('identity').textContent=`Seed ${x.seed} · Config ${x.config_hash} · GNN ${x.models.gnn_sha256} · Model scope: ${x.models.validation_scope}`;
  $('artifacts').innerHTML=c.final?Object.entries(x.artifact_urls).map(([policy,urls])=>`<div><b>${esc(policy)}</b> ${Object.entries(urls).map(([name,url])=>`<a href="${esc(url)}" download>${esc(name)}</a>`).join('')}</div>`).join('')+`<a href="/api/research/sessions/${esc(x.session_id)}/evidence/config.json" download>Scenario config</a><a href="/api/research/sessions/${esc(x.session_id)}/evidence/comparison.json" download>Paired comparison</a>`:'Raw events and versioned run manifests are available after this run completes.';
}

function renderTransport(){const x=state.snapshot,complete=x?.phase==='COMPLETE';document.body.dataset.paused=String(state.paused);
  $('pause').disabled=state.starting||complete&&!state.error;$('pause').textContent=state.starting?'Starting…':state.error?'Retry':complete?'Complete':state.paused?'▶ Resume':'Ⅱ Pause';$('pause').setAttribute('aria-pressed',String(state.paused));
  $('restart').disabled=state.busy;for(const id of ['scenario','device-count','task-mix','task-rate'])$(id).disabled=state.starting;$('step-once').disabled=!x||!state.paused||state.busy||Boolean(state.error)||complete;
  $('phase').textContent=state.starting?'Starting':state.error?'Stopped':!x?'Starting':complete?'Complete':state.paused?(state.busy?'Pausing…':'Paused'):x.phase==='DRAIN'?'Finishing jobs':'Running';}
function render(x){if(!x)return;renderTransport();$('clock').textContent=(x.time_us/1e6).toFixed(3)+' s';const progress=Math.min(100,x.time_us/x.end_us*100);$('progress').style.width=progress+'%';$('run-progress').setAttribute('aria-valuenow',progress.toFixed(1));
  if(state.view==='simulation'){renderBoard(x);renderInspector(x);$('running-count').textContent=x.after.tasks.filter(t=>t.state==='RUNNING').length;$('done-count').textContent=x.after.metrics.committed_tasks;$('scenario-label').textContent=(state.scenarioMode==='recovery'?'Recovery stress · peers slow at 98 ms':x.family)+' · seed '+x.seed;
    const events=x.after.events.slice(-8).reverse();$('activity-count').textContent='· '+events.length;$('events').innerHTML=events.map(e=>`<div class="event"><time>${(e.timestamp_us/1e6).toFixed(3)} s</time><div>${esc(e.event_type.toLowerCase().replaceAll('_',' '))}<small>${esc(e.device_id||'fleet')} ${esc(e.task_id?.split('/').pop()||'')}</small></div></div>`).join('');
  }else renderResults(x);
}
function accept(x){const now=performance.now();packetDuration=Math.min(250,Math.max(34,now-acceptedAt));acceptedAt=now;acceptFacilityTime(x);state.snapshot=x;$('scenario').value=state.scenarioMode||x.family;if(!x.workflows.some(w=>w.pipeline_id===state.workflow))state.workflow=x.workflows[0].pipeline_id;
  if($('workflow').dataset.config!==x.config_hash){$('workflow').dataset.config=x.config_hash;$('workflow').innerHTML=x.workflows.map(w=>`<option value="${esc(w.pipeline_id)}">${esc(w.pipeline_id[0].toUpperCase()+w.pipeline_id.slice(1))}</option>`).join('');}$('workflow').value=state.workflow;
  const interesting=new Set(['WATCHDOG_ABORT','WATCHDOG_CHECK','FALLBACK_ADMITTED','EARLY_EXIT','TASK_COMMIT','OFFLOAD_DISPATCH','OUTPUT_VALIDATION']);
  const seen=new Set(state.protectionEvents.map(e=>e.sequence));for(const e of x.after.events){if(interesting.has(e.event_type)&&!seen.has(e.sequence))state.protectionEvents.push(e);}state.protectionEvents=state.protectionEvents.slice(-3000);
  const eventType=$('protection-stop').value==='watchdog'?'WATCHDOG_ABORT':'EARLY_EXIT';
  const newest=x.after.events.filter(e=>e.event_type===eventType&&e.sequence>(state.lastProtectionSequence||0)).at(-1);
  if(newest&&$('pause-recovery').checked&&!state.starting){state.paused=true;state.protectionTask=newest.task_id;state.selectedTask=newest.task_id;const task=x.after.tasks.find(t=>t.id===newest.task_id);if(task){state.device=task.device;state.workflow=x.after.jobs.find(j=>j.id===task.job)?.workflow||state.workflow;}$('workflow').value=state.workflow;stopMotion();}
  state.lastProtectionSequence=Math.max(state.lastProtectionSequence||0,...x.after.events.map(e=>e.sequence));
  const sample={t:x.time_us,a:x.before.metrics.job_dmr_pct,b:x.after.metrics.job_dmr_pct};if(state.history.at(-1)?.t===x.time_us)state.history[state.history.length-1]=sample;else state.history.push(sample);render(x);}
function fail(e){state.error=e.message;state.paused=true;stopMotion();if(state.snapshot)$('scenario').value=state.scenarioMode||state.snapshot.family;$('error').hidden=false;$('error').textContent='Simulation stopped: '+e.message;renderTransport();}
function stopMotion(){document.getAnimations().forEach(a=>a.cancel());}
async function advance(delta){if(state.busy||state.error||!state.snapshot||state.snapshot.phase==='COMPLETE')return;state.busy=true;renderTransport();try{accept(await request('/api/research/sessions/'+state.snapshot.session_id+'/step',{delta_us:delta}));}catch(e){fail(e);}finally{state.busy=false;renderTransport();if(state.pendingRestart){state.pendingRestart=false;start();}}}
async function stepSimulationOnce(){if(!state.paused)return;await advance(1000);}
async function start(){if(state.busy)return;const old=state.snapshot?.session_id;state.busy=true;state.starting=true;state.error=null;state.paused=true;$('error').hidden=true;stopMotion();renderTransport();
  try{const mode=$('scenario').value;const template=await request('/api/research/scenarios/templates/'+(mode==='recovery'?'unreliable':mode));const scenario=configureGroundScenario(template,Number($('device-count').value),$('task-mix').value,Number($('task-rate').value),mode==='recovery');const x=await request('/api/research/sessions',{scenario,baseline:'edf'});state.scenarioMode=mode;state.history=[];state.selectedTask=null;state.protectionTask=null;state.protectionEvents=[];state.lastProtectionSequence=0;ground.key='';state.zoom=1;state.paused=false;accept(x);$('canvas-scroll').scrollTo(0,0);if(old)fetch('/api/research/sessions/'+old,{method:'DELETE'}).catch(()=>{});}catch(e){fail(e);}finally{state.busy=false;state.starting=false;renderTransport();}}
function selectView(view,focus=false){state.view=view;for(const key of ['simulation','results']){$('tab-'+key).setAttribute('aria-selected',String(view===key));$('tab-'+key).tabIndex=view===key?0:-1;$('view-'+key).hidden=view!==key;}if(focus)$('tab-'+view).focus();render(state.snapshot);}
$('pause').onclick=()=>{if(state.error){if(state.snapshot){state.error=null;$('error').hidden=true;state.paused=false;}else{start();return;}}else state.paused=!state.paused;stopMotion();render(state.snapshot);renderTransport();};
function restartForSettings(){if(state.busy){state.pendingRestart=true;state.paused=true;renderTransport();}else start();}
$('step-once').onclick=stepSimulationOnce;$('restart').onclick=start;for(const id of ['scenario','device-count','task-mix','task-rate'])$(id).onchange=restartForSettings;
$('playback-speed').oninput=()=>{$('speed-label').textContent=Number($('playback-speed').value).toFixed(2)+'×';};$('task-rate').oninput=()=>{$('task-rate-label').textContent=$('task-rate').value+'%';};$('slow-motion').onclick=()=>{$('playback-speed').value='0.05';$('playback-speed').oninput();$('pause-recovery').checked=true;};$('inspect-device').onchange=()=>selectGroundDevice($('inspect-device').value);
$('workflow').onchange=()=>{state.workflow=$('workflow').value;state.selectedTask=null;state.protectionTask=null;render(state.snapshot);};
$('close-inspector').onclick=()=>{state.selectedTask=null;state.protectionTask=null;render(state.snapshot);};
for(const v of ['simulation','results']){$('tab-'+v).onclick=()=>selectView(v);$('tab-'+v).onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();selectView(e.key==='Home'?'simulation':e.key==='End'?'results':state.view==='simulation'?'results':'simulation',true);}};}
$('zoom-in').onclick=()=>zoomGround(1.25);$('zoom-out').onclick=()=>zoomGround(.8);$('zoom-reset').onclick=()=>{ground.camera={x:0,y:0,scale:1};applyGroundCamera();};$('focus-device').onclick=focusGroundDevice;$('device-motion').onchange=()=>{animateFacility(performance.now(),true);};$('reset-nodes').onclick=()=>{facility.manual.clear();ground.positions=groundPositions(state.snapshot.devices);moveGroundDevices();renderConnections(state.snapshot);};
window.addEventListener('resize',()=>{if(state.snapshot&&state.view==='simulation')renderBoard(state.snapshot);});
const family=new URLSearchParams(location.search).get('family');if(['nominal','bursty','thermal','unreliable'].includes(family))$('scenario').value=family;
// One request at a time, aligned with repaint. Hidden browser tabs do no work.
function frame(now){animateFacility(now);if(now-lastFrame>=34){lastFrame=now;if(!document.hidden&&!state.paused&&!state.busy&&!state.error&&state.snapshot?.phase!=='COMPLETE')advance(Math.round(1500*Number($('playback-speed').value)));}requestAnimationFrame(frame);}
window.addEventListener('pagehide',()=>{if(state.snapshot)fetch('/api/research/sessions/'+state.snapshot.session_id,{method:'DELETE',keepalive:true}).catch(()=>{});});
start();requestAnimationFrame(frame);
