/* A spatial presentation of canonical simulator records, not a physical/RF model. */
const ground={width:1200,height:690,positions:{},camera:{x:0,y:0,scale:1},key:'',taskKey:'',pointers:new Map(),gesture:null,suppressClick:false};

function groundPositions(devices){return facilityPositions(devices);}

function resourceUsage(sample){
  const known=sample?.at_us!=null;
  return {known,cpu:known?Math.max(0,Math.min(100,(sample.cpu_ppm||0)/10000)):null,gpu:known?Math.max(0,Math.min(100,(sample.gpu_ppm||0)/10000)):null,at_us:sample?.at_us};
}
function groundRoute(a,b,lane=0){
  const dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy)||1;
  const from=[a.x+dx/len*37,a.y+dy/len*37],to=[b.x-dx/len*44,b.y-dy/len*44];
  const control=[(from[0]+to[0])/2-dy/len*lane,(from[1]+to[1])/2+dx/len*lane];
  return {path:`M${from} Q${control} ${to}`,point:f=>from.map((v,i)=>(1-f)**2*v+2*(1-f)*f*control[i]+f*f*to[i])};
}
function protectionRecord(x,taskId=null,archive=[]){
  const hands=x.after.handoffs||[],tasks=x.after.tasks;
  let task=tasks.find(t=>t.id===taskId),handoff=task?hands.filter(h=>h.task===task.id).at(-1):null;
  if(!task){handoff=[...hands].filter(h=>h.events.some(e=>e.event_type==='WATCHDOG_ABORT')).sort((a,b)=>a.events.filter(e=>e.event_type==='WATCHDOG_ABORT').at(-1).timestamp_us-b.events.filter(e=>e.event_type==='WATCHDOG_ABORT').at(-1).timestamp_us).at(-1);
    if(handoff)task=tasks.find(t=>t.id===handoff.task);
    if(!task){task=tasks.filter(t=>t.fallback_admitted).sort((a,b)=>a.fallback_admitted.at_us-b.fallback_admitted.at_us).at(-1);handoff=task?hands.filter(h=>h.task===task.id).at(-1):hands.at(-1);if(!task&&handoff)task=tasks.find(t=>t.id===handoff.task);}}
  const events=[...(handoff?.events||[]),...archive,...(x.after.events||[])].filter(e=>e.task_id===task?.id),find=k=>events.find(e=>e.event_type===k);
  const timestamp=(event,record)=>event?.timestamp_us??record?.at_us??null;
  const abort=find('WATCHDOG_ABORT'),check=events.filter(e=>e.event_type==='WATCHDOG_CHECK').at(-1);
  const steps=abort?[
    ['OFFLOAD_DISPATCH','Remote request',timestamp(find('OFFLOAD_DISPATCH'))],
    ['WATCHDOG_ABORT','Watchdog abort',timestamp(abort)],
    ['FALLBACK_ADMITTED','Local fallback',timestamp(find('FALLBACK_ADMITTED'),task?.fallback_admitted)],
    ['EARLY_EXIT','Early exit',timestamp(find('EARLY_EXIT'))],
    ['TASK_COMMIT','Result committed',task?.commit_us??null]
  ]:task?.fallback_admitted?[
    ['DECISION','Local decision',task.diagnostics?.decision?.at_us??null],
    ['FALLBACK_ADMITTED','Exit admitted',task.fallback_admitted.at_us],
    ['EARLY_EXIT','Early exit',timestamp(find('EARLY_EXIT'))],
    ['OUTPUT_VALIDATION','Output validated',task.output_validation?.valid?task.output_validation.at_us:null],
    ['TASK_COMMIT','Result committed',task.commit_us??null]
  ]:[['OFFLOAD_DISPATCH','Remote request',timestamp(find('OFFLOAD_DISPATCH'))],['WATCHDOG_CHECK','Watchdog check',timestamp(check)],['FALLBACK_ADMITTED','Local fallback',null],['EARLY_EXIT','Early exit',null],['TASK_COMMIT','Result committed',task?.commit_us??null]];
  return {task,handoff,abort,check,steps};
}

function buildGroundMap(x){
  if(ground.key===x.config_hash)return;
  ground.key=x.config_hash;ground.taskKey='';ground.positions=groundPositions(x.devices);facility.manual.clear();ground.camera={x:0,y:0,scale:1};ground.pointers.clear();ground.gesture=null;previousPackets.clear();
  const svg=$('simulation-canvas');svg.setAttribute('viewBox','0 0 1200 760');
  let html='<defs><marker id="dependency-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L8 4L0 8Z" fill="context-stroke"/></marker><filter id="device-shadow"><feDropShadow dx="0" dy="3" stdDeviation="4" flood-color="#64748b" flood-opacity=".16"/></filter></defs><g id="ground-camera">'+facilitySceneSvg()+'<g id="live-links"></g><g id="recovery-links"></g><g id="device-cards">';
  x.devices.forEach((d,i)=>{const c=colors[i%colors.length],kind=['drone','server','rover','arm','chip','station'].includes(d.kind)?d.kind:'chip';
    html+=`<g class="ground-device" data-device="${esc(d.device_id)}" role="button" tabindex="0" aria-label="Select ${esc(d.name)}" transform="translate(${ground.positions[d.device_id].x} ${ground.positions[d.device_id].y})"><title>Drag to reposition ${esc(d.name)}. Arrow keys move the selected device.</title><ellipse cx="0" cy="33" rx="40" ry="9" fill="#526483" opacity=".13"/><circle class="device-halo" r="45" fill="${c}" fill-opacity=".09" stroke="${c}" stroke-opacity=".25"/><circle class="device-face" r="31" fill="white" stroke="${c}" stroke-width="2" filter="url(#device-shadow)"/>${facilityDeviceSvg(kind,c)}<path class="device-label-stem" stroke="${c}" stroke-opacity=".35" fill="none"/><g class="device-label-panel"><rect x="-94" y="48" width="188" height="127" rx="12" fill="white" stroke="${c}" stroke-opacity=".38" filter="url(#device-shadow)"/><text x="0" y="69" text-anchor="middle" font-size="13" font-weight="650" fill="#263753">${esc(d.name)}</text><text data-cpu-label x="-80" y="89" font-size="10" fill="#64748b">CPU</text><text data-gpu-label x="13" y="89" font-size="10" fill="#64748b">GPU</text><rect x="-80" y="98" width="72" height="5" rx="2.5" fill="#e5eaf4"/><rect data-cpu-bar x="-80" y="98" width="0" height="5" rx="2.5" fill="#3b82f6"/><rect x="13" y="98" width="72" height="5" rx="2.5" fill="#e5eaf4"/><rect data-gpu-bar x="13" y="98" width="0" height="5" rx="2.5" fill="#a855f7"/><text data-device-status x="0" y="119" text-anchor="middle" font-size="9" fill="#64748b"></text><text data-live-cpu-task x="-80" y="139" font-size="10" fill="#2563eb"></text><text data-live-gpu-task x="-80" y="157" font-size="10" fill="#9333ea"></text></g></g>`;});
  svg.innerHTML=html+'</g></g>';installGroundGestures(svg);applyGroundCamera();
  $('inspect-device').innerHTML=x.devices.map(d=>`<option value="${esc(d.device_id)}">${esc(d.name)}</option>`).join('');
  if(!x.devices.some(d=>d.device_id===state.device))state.device=x.devices[0].device_id;
  svg.querySelectorAll('[data-device]').forEach(el=>{el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectGroundDevice(el.dataset.device);}else if(e.key.startsWith('Arrow')){e.preventDefault();e.stopPropagation();const p=ground.positions[el.dataset.device],delta=e.shiftKey?25:10;p.x+=e.key==='ArrowRight'?delta:e.key==='ArrowLeft'?-delta:0;p.y+=e.key==='ArrowDown'?delta:e.key==='ArrowUp'?-delta:0;facility.manual.add(el.dataset.device);moveGroundDevices();renderGroundConnections(state.snapshot);}};});
}
function selectGroundDevice(id){state.device=id;state.selectedTask=null;state.protectionTask=null;render(state.snapshot);}
function moveGroundDevices(){document.querySelectorAll('.ground-device').forEach(el=>{const p=ground.positions[el.dataset.device];el.setAttribute('transform',`translate(${p.x} ${p.y})`);});arrangeFacilityLabels();}
function applyGroundCamera(){$('ground-camera')?.setAttribute('transform',`translate(${ground.camera.x} ${ground.camera.y}) scale(${ground.camera.scale})`);state.zoom=ground.camera.scale;}
function mapPoint(event){const p=$('simulation-canvas').createSVGPoint();p.x=event.clientX;p.y=event.clientY;return p.matrixTransform($('simulation-canvas').getScreenCTM().inverse());}
function zoomGround(factor,anchor={x:600,y:345}){const c=ground.camera,next=Math.max(.4,Math.min(4,c.scale*factor));c.x=anchor.x-(anchor.x-c.x)*next/c.scale;c.y=anchor.y-(anchor.y-c.y)*next/c.scale;c.scale=next;applyGroundCamera();}
function focusGroundDevice(){const p=ground.positions[state.device];if(!p)return;const scale=matchMedia('(max-width:760px)').matches?3:2;ground.camera={x:600-p.x*scale,y:280-p.y*scale,scale};applyGroundCamera();}
function installGroundGestures(svg){
  svg.onwheel=e=>{e.preventDefault();zoomGround(Math.exp(-e.deltaY*.0015),mapPoint(e));};
  svg.onpointerdown=e=>{if(e.button!==0&&e.pointerType!=='touch')return;e.preventDefault();svg.setPointerCapture(e.pointerId);ground.pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});const node=e.target.closest('[data-device]'),p=mapPoint(e);if(node)node.focus();ground.gesture={device:node?.dataset.device,start:p,last:p,moved:false};
    if(ground.pointers.size===2){ground.gesture.device=null;ground.gesture.moved=true;const [a,b]=[...ground.pointers.values()];ground.pinch=Math.hypot(a.x-b.x,a.y-b.y);}};
  svg.onpointermove=e=>{if(!ground.pointers.has(e.pointerId))return;ground.pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
    if(ground.pointers.size===2){const [a,b]=[...ground.pointers.values()],distance=Math.hypot(a.x-b.x,a.y-b.y);if(ground.pinch>0)zoomGround(distance/ground.pinch,mapPoint({clientX:(a.x+b.x)/2,clientY:(a.y+b.y)/2}));ground.pinch=distance;return;}
    const g=ground.gesture;if(!g)return;const p=mapPoint(e),dx=p.x-g.last.x,dy=p.y-g.last.y;if(Math.hypot(p.x-g.start.x,p.y-g.start.y)>4)g.moved=true;
    if(g.moved){if(g.device){facility.manual.add(g.device);const pos=ground.positions[g.device];pos.x=Math.max(-400,Math.min(1600,pos.x+dx/ground.camera.scale));pos.y=Math.max(-300,Math.min(990,pos.y+dy/ground.camera.scale));moveGroundDevices();renderGroundConnections(state.snapshot);}else{ground.camera.x+=dx;ground.camera.y+=dy;applyGroundCamera();}}g.last=p;};
  const finish=e=>{const g=ground.gesture;ground.pointers.delete(e.pointerId);if(e.type!=='pointercancel'&&g?.device&&!g.moved)selectGroundDevice(g.device);if(!ground.pointers.size)ground.gesture=null;else{const p=[...ground.pointers.values()][0];ground.gesture={device:null,start:mapPoint({clientX:p.x,clientY:p.y}),last:mapPoint({clientX:p.x,clientY:p.y}),moved:true};}};
  svg.onpointerup=finish;svg.onpointercancel=finish;
  $('canvas-scroll').onkeydown=e=>{if(e.target.closest('[data-device]'))return;const c=ground.camera;if(['+','=','-','0','Home','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();if(e.key==='+'||e.key==='=')zoomGround(1.2);else if(e.key==='-')zoomGround(1/1.2);else if(e.key==='0'||e.key==='Home'){ground.camera={x:0,y:0,scale:1};applyGroundCamera();}else{c.x+=e.key==='ArrowLeft'?30:e.key==='ArrowRight'?-30:0;c.y+=e.key==='ArrowUp'?30:e.key==='ArrowDown'?-30:0;applyGroundCamera();}}};
}

function renderGroundMap(x){buildGroundMap(x);$('inspect-device').value=state.device;
  document.querySelectorAll('.ground-device').forEach(el=>{const id=el.dataset.device,usage=resourceUsage(x.after.resources[id]);el.dataset.sampleUs=usage.at_us??'';
    for(const k of ['cpu','gpu']){el.querySelector(`[data-${k}-label]`).textContent=k.toUpperCase()+' '+(usage[k]==null?'—':usage[k].toFixed(0)+'%');el.querySelector(`[data-${k}-bar]`).setAttribute('width',usage[k]==null?0:usage[k]*.72);el.dataset[k+'Usage']=usage[k]??'';}
    const jobs=x.after.jobs.filter(j=>j.device===id&&j.status==='ACTIVE');el.querySelector('[data-device-status]').textContent=jobs.length+' active jobs · '+x.after.tasks.filter(t=>t.device===id&&t.state==='RUNNING').length+' running';el.querySelector('.device-face').setAttribute('stroke-width',state.device===id?'4':'2');el.classList.toggle('device-selected',state.device===id);const owners=activeDeviceTasks(x,id);for(const owner of owners){const text=el.querySelector('[data-live-'+owner.lane+'-task]');text.textContent=owner.lane.toUpperCase()+' · '+taskName(owner.label)+(owner.origin&&owner.origin!==id?' ← '+owner.origin.replace('Device_','N'):'');text.dataset.ownerTask=owner.task||'';}});
  animateFacility(performance.now(),state.paused);renderGroundConnections(x);renderDeviceTasks(x);renderOtherWorkflows(x);renderProtectionFlow(x);arrangeFacilityLabels();
}
function renderGroundConnections(x){
  if(!x||!$('live-links'))return;const next=new Map();let html='';
  liveTransfers(x).forEach(t=>{const a=ground.positions[t.source],b=ground.positions[t.target];if(!a||!b)return;const key=t.id||[t.source,t.target,t.phase,t.start_us,t.task].join('|'),lane=[...key].reduce((n,c)=>n+c.charCodeAt(0),0)%3*14-14,route=groundRoute(a,b,lane),f=transferFraction(t,x),p=route.point(f),c=t.phase==='result'?'#059669':t.phase==='cancel'?'#ef4444':t.phase.startsWith('fl_')?'#a855f7':'#3b82f6';next.set(key,p);
    html+=`<g data-transfer="${esc(key)}" data-source="${esc(t.source)}" data-target="${esc(t.target)}" data-fraction="${f}" data-lane="${lane}"><title>${esc(t.source+' → '+t.target+' · '+t.phase+' · '+(t.task||'learning'))}</title><path d="${route.path}" stroke="${c}" stroke-width="3" fill="none" stroke-opacity=".7" marker-end="url(#dependency-arrow)"/><circle cx="${p[0]}" cy="${p[1]}" r="5" fill="${c}" stroke="white" stroke-width="2"/></g>`;});
  $('live-links').innerHTML=html;
  if(!state.paused&&!ground.gesture&&!matchMedia('(prefers-reduced-motion:reduce)').matches){$('live-links').querySelectorAll('[data-transfer]').forEach(el=>{const old=previousPackets.get(el.dataset.transfer),p=next.get(el.dataset.transfer);if(old)el.querySelector('circle').animate([{transform:`translate(${old[0]-p[0]}px,${old[1]-p[1]}px)`},{transform:'translate(0,0)'}],{duration:packetDuration,easing:'linear'});});}
  previousPackets=next;$('live-count').textContent=liveTransfers(x).length;
  const record=protectionRecord(x,state.protectionTask,state.protectionEvents),h=record.handoff,a=h&&ground.positions[h.target],b=h&&ground.positions[h.origin];
  $('recovery-links').innerHTML=record.abort&&a&&b?`<g data-recovery-task="${esc(record.task?.id)}" data-source="${esc(h.target)}" data-target="${esc(h.origin)}"><path d="${groundRoute(a,b,55).path}" stroke="#f97316" stroke-width="3" stroke-dasharray="7 5" fill="none" marker-end="url(#dependency-arrow)"/><title>Recorded watchdog abort: local fallback on ${esc(h.origin)}. This mechanism arrow is not a network packet.</title>${svgText((a.x+b.x)/2,(a.y+b.y)/2+38,'Watchdog → local fallback',11,'#c2410c',650)}</g>`:'';
}
function renderDeviceTasks(x){
  const w=x.workflows.find(w=>w.pipeline_id===state.workflow),d=x.devices.find(d=>d.device_id===state.device),selected=x.after.tasks.find(t=>t.id===state.selectedTask);
  const job=selected&&selected.device===state.device&&x.after.jobs.find(j=>j.id===selected.job)?.workflow===state.workflow?x.after.jobs.find(j=>j.id===selected.job):x.after.jobs.filter(j=>j.device===state.device&&j.workflow===state.workflow).at(-1);
  const ts=x.after.tasks.filter(t=>t.job===job?.id),layout=dependencyLayout(w,1000,138,90),svg=$('task-graph'),key=x.config_hash+'|'+state.workflow+'|'+state.device;
  $('device-task-title').textContent=d.name+' → '+w.pipeline_id;$('device-task-caption').textContent=job?'Job '+job.id.split('/').pop()+' · '+job.status.toLowerCase()+' · arrows require committed results':'Waiting for this workflow to release';
  if(ground.taskKey!==key){ground.taskKey=key;svg.setAttribute('viewBox',`0 0 ${layout.width} ${layout.height+30}`);let html='';
    w.dependency_edges.forEach(([a,b])=>{const [ax,ay]=layout.positions[a],[bx,by]=layout.positions[b];html+=`<path data-edge-source="${esc(a)}" data-edge-target="${esc(b)}" d="M${ax+138} ${ay+25} C${ax+168} ${ay+25},${bx-25} ${by+25},${bx} ${by+25}" fill="none" stroke="#cbd5e1" stroke-width="2" marker-end="url(#dependency-arrow)"/>`;});
    w.tasks.forEach(spec=>{const [tx,ty]=layout.positions[spec.task_id];html+=`<g class="task-node" data-stage="${esc(spec.task_id)}" role="button" tabindex="0"><title></title><rect class="task-box" x="${tx}" y="${ty}" width="138" height="60" rx="9" fill="white" stroke="#cbd5e1"/>${svgText(tx+9,ty+20,taskName(spec.task_id),10,'#17243b',600)}<text data-task-status x="${tx+9}" y="${ty+38}" font-size="10"></text><text data-work-label x="${tx+9}" y="${ty+52}" font-size="9" fill="#64748b"></text></g>`;});svg.innerHTML=html;
    svg.querySelectorAll('.task-node').forEach(node=>{const pick=()=>{if(!node.dataset.task)return;state.selectedTask=node.dataset.task;state.protectionTask=node.dataset.task;render(state.snapshot);};node.onclick=pick;node.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();pick();}};});}
  svg.querySelectorAll('.task-node').forEach(node=>{const t=ts.find(t=>t.name===node.dataset.stage),s=taskVisualState(t),c=statusColors[s]||'#94a3b8';node.dataset.task=t?.id||'';node.dataset.state=t?.state||'BLOCKED';node.setAttribute('aria-label',node.dataset.stage+': '+(t?statusNames[s]:'Not released'));node.querySelector('[data-task-status]').textContent=(t?statusNames[s]:'Not released')+(t?.host&&t.host!==state.device?' → '+t.host.replace('Device_','D'):'');node.querySelector('[data-task-status]').setAttribute('fill',c);node.querySelector('.task-box').setAttribute('fill',c+'0d');node.querySelector('.task-box').setAttribute('stroke',state.selectedTask===t?.id?'#7c3aed':c+'80');const spec=w.tasks.find(s=>s.task_id===node.dataset.stage);node.querySelector('[data-work-label]').textContent=spec.resource_demands.some(r=>r.resource==='gpu')?(t?.degraded?'GPU · early-exit path':'GPU · 4 layers'):'CPU';node.querySelector('title').textContent=t?.id||node.dataset.stage;});
  svg.querySelectorAll('[data-edge-source]').forEach(el=>{const ready=ts.find(t=>t.name===el.dataset.edgeSource)?.state==='COMMITTED';el.dataset.predecessorCommitted=String(ready);el.setAttribute('stroke',ready?'#10b981':'#b7c4d5');el.setAttribute('stroke-dasharray',ready?'':'5 4');});
}
function renderProtectionFlow(x){const r=protectionRecord(x,state.protectionTask,state.protectionEvents),t=r.task;
  $('protection-title').textContent=r.abort?'Watchdog → fallback → early exit':t?.fallback_admitted?'Local early-exit path':r.handoff?'Watching a remote task':'Waiting for a protection event';
  $('protection-caption').textContent=t?taskName(t.name)+' · '+t.device+(r.handoff?' → '+r.handoff.target:'')+' · '+(r.abort?.payload?.reason||r.check?.payload?.reason||'Recorded local decision').replaceAll('_',' '):'Use slow motion and pause after a protection event to inspect actual recovery. No intervention has been recorded yet.';
  $('protection-flow').innerHTML=r.steps.map(([key,label,time],i)=>`<div class="protection-step ${time!=null?'observed':''}" data-protection-milestone="${key}" data-observed="${time!=null}" data-event-us="${time??''}"><span class="step-index">${time!=null?'✓':i+1}</span><strong>${esc(label)}</strong><small>${time==null?'Not recorded':ms(time)}</small></div>`).join('<span class="flow-arrow" aria-hidden="true">→</span>');
  const cancellation=r.handoff?.events.some(e=>e.event_type==='CANCEL_ACK')?'Cancellation acknowledged':r.handoff?.events.some(e=>e.event_type==='CANCEL_REQUEST')?'Cancellation requested':'No cancellation recorded';
  $('protection-outcome').textContent=t?(t.state==='COMMITTED'?'Task result committed':t.state==='MISSED'?'Task deadline missed':t.state==='SKIPPED'?'Task skipped':'Task is still active')+' · '+cancellation+'. Local fallback is separate from network cancellation; task recovery does not imply the whole job met its deadline.':'';
}

function configureGroundScenario(template,count,mix,rate,stress=false){
  const scenario=structuredClone(template),base=scenario.devices;
  scenario.devices=Array.from({length:count},(_,i)=>({...base[i%base.length],device_id:'Device_'+(i+1),name:i<base.length?base[i].name:({4:'Delivery rover',5:'Factory robot',6:'Roadside edge',7:'Inspection drone'})[i],kind:i<base.length?base[i].kind:({4:'rover',5:'arm',6:'station',7:'drone'})[i]}));
  const ids=new Set(scenario.devices.map(d=>d.device_id));scenario.faults=scenario.faults.filter(f=>ids.has(f.device_id));
  if(stress){scenario.faults=scenario.faults.filter(f=>f.device_id==='Device_1');
    scenario.faults.push(...scenario.devices.slice(1).map(d=>({device_id:d.device_id,start_us:98000,end_us:300000,cpu_ppm:700000,gpu_ppm:950000,extra_link_us:20000,loss_ppm:200000})));}
  if(mix!=='mixed')scenario.workflows=scenario.workflows.filter(w=>w.pipeline_id===mix);
  scenario.workflows.forEach(w=>{w.period_us=Math.max(10000,Math.round(w.period_us*100/rate));});
  return scenario;
}
