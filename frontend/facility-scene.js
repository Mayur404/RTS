/* Facility geometry and travel are illustrative; they do not alter runtime evidence. */
const facility={fromUs:0,targetUs:0,timeUs:0,receivedAt:0,manual:new Set(),lastDraw:0};

function facilityPositions(devices){
  const locations={drone:[[310,295],[800,400]],server:[[540,88],[670,85]],rover:[[160,275],[980,575]],arm:[[360,405],[840,405]],station:[[1070,102]],chip:[[540,88]]};
  const counts={},positions={};
  devices.forEach(d=>{const kind=locations[d.kind]?d.kind:'chip',i=counts[kind]||0;counts[kind]=i+1;const p=locations[kind][i%locations[kind].length];positions[d.device_id]={x:p[0]+Math.floor(i/locations[kind].length)*55,y:p[1]};});
  return positions;
}
function pointOnFacilityPath(points,fraction){
  const pairs=points.map((p,i)=>[p,points[(i+1)%points.length]]),lengths=pairs.map(([a,b])=>Math.hypot(b[0]-a[0],b[1]-a[1]));
  let remaining=((fraction%1)+1)%1*lengths.reduce((a,b)=>a+b,0);
  for(let i=0;i<pairs.length;i++){if(remaining<=lengths[i]||i===pairs.length-1){const [a,b]=pairs[i],f=lengths[i]?remaining/lengths[i]:0;return {x:a[0]+(b[0]-a[0])*f,y:a[1]+(b[1]-a[1])*f,heading:Math.atan2(b[1]-a[1],b[0]-a[0])*180/Math.PI};}remaining-=lengths[i];}
}
function facilityDevicePosition(device,index,timeUs){
  const fraction=timeUs/900000+index*.19;
  if(device.kind==='rover')return pointOnFacilityPath([[140,275],[1060,275],[1060,565],[140,565]],fraction);
  if(device.kind==='drone')return pointOnFacilityPath([[270,295],[480,310],[640,390],[550,490],[270,450],[185,370]],fraction);
  return null;
}
function facilityDeviceSvg(kind,color){
  if(kind==='rover')return `<g class="mobile-vehicle"><rect x="-13" y="-15" width="9" height="5" rx="2" fill="#34445a"/><rect x="7" y="-15" width="9" height="5" rx="2" fill="#34445a"/><rect x="-13" y="10" width="9" height="5" rx="2" fill="#34445a"/><rect x="7" y="10" width="9" height="5" rx="2" fill="#34445a"/><rect x="-21" y="-11" width="43" height="22" rx="7" fill="${color}" stroke="#fff" stroke-width="1.5"/><rect x="-10" y="-8" width="17" height="16" rx="3" fill="#edf5fc"/><path d="M9-8L15-6V6L9 8Z" fill="#b5d3e9"/><path d="M19-6V-3M19 3V6" stroke="#fff8c0" stroke-width="2"/></g>`;
  if(kind==='drone'){let svg='<g class="mobile-drone"><path d="M-14-14L14 14M-14 14L14-14" stroke="#64748b" stroke-width="4"/>';
    for(const [x,y]of [[-14,-14],[14,-14],[-14,14],[14,14]])svg+=`<circle cx="${x}" cy="${y}" r="8" fill="#f0f5fb" stroke="#8ba0b6"/><g class="drone-rotor" data-cx="${x}" data-cy="${y}"><path d="M${x-6} ${y}H${x+6}" stroke="#64748b" stroke-width="2" stroke-linecap="round"/></g>`;
    return svg+`<rect x="-7" y="-8" width="14" height="16" rx="4" fill="${color}" stroke="white" stroke-width="1.5"/><circle cy="-3" r="2" fill="#dbeafe"/></g>`;}
  return `<image href="/static/icons/${kind}.svg" x="-23" y="-23" width="46" height="46"/>`;
}
function activeDeviceTasks(x,id){
  const sample=x.after.resources[id];if(sample?.at_us==null)return [];
  return ['cpu','gpu'].map(lane=>{const slot=sample[lane+'_slot'];if(!slot)return {lane,task:null,label:(sample['background_'+lane+'_ppm']||0)>0?'Background load':lane==='cpu'&&(sample.gpu_cpu_reservation_ppm||0)>0?'GPU reservation':'Idle'};
    const attempt=x.after.attempts.find(a=>a.id===slot),operation=sample.operations?.find(o=>o.id===slot),task=x.after.tasks.find(t=>t.id===(attempt?.task||operation?.task));
    return {lane,task:task?.id||null,label:task?task.name:(operation?.kind||'Controller'),operation:operation?.kind||null,origin:task?.device||null};});
}
function facilityLabelLayout(positions,devices,selected){
  const placed=[],result={},width=188,height=127;
  const overlap=(a,b)=>Math.max(0,Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x))*Math.max(0,Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y));
  const ordered=[...devices].sort((a,b)=>(b.device_id===selected)-(a.device_id===selected));
  for(const d of ordered){const p=positions[d.device_id],candidates=[{x:-94,y:48},{x:-94,y:-177},{x:48,y:-30},{x:-236,y:-30}];let best=null;
    for(const offset of candidates){const box={x:p.x+offset.x,y:p.y+offset.y,w:width,h:height};let score=(box.x<38||box.x+width>1162||box.y<30||box.y+height>726)?100000:0;
      score+=placed.reduce((sum,b)=>sum+overlap(box,b),0)*5;
      for(const other of devices){const q=positions[other.device_id];score+=overlap(box,{x:q.x-35,y:q.y-35,w:70,h:70})*10;}
      if(!best||score<best.score)best={box,offset,score};}
    placed.push(best.box);result[d.device_id]=best.offset;
  }
  return result;
}
function arrangeFacilityLabels(){
  if(!state.snapshot)return;const offsets=facilityLabelLayout(ground.positions,state.snapshot.devices,state.device);
  document.querySelectorAll('.ground-device').forEach(el=>{const o=offsets[el.dataset.device];if(!o)return;el.querySelector('.device-label-panel')?.setAttribute('transform',`translate(${o.x+94} ${o.y-48})`);const tx=Math.max(o.x,Math.min(o.x+188,0)),ty=Math.max(o.y,Math.min(o.y+127,0)),len=Math.hypot(tx,ty)||1;el.querySelector('.device-label-stem')?.setAttribute('d',`M${tx/len*32} ${ty/len*32}L${tx} ${ty}`);});
}
function facilitySceneSvg(){
  const text=(x,y,label,size=11,color='#7b8d99')=>`<text x="${x}" y="${y}" font-size="${size}" fill="${color}" font-family="inherit">${label}</text>`;
  const building=(x,y,w,h,title,color,roof)=>`<g class="facility-building"><rect x="${x+5}" y="${y+7}" width="${w}" height="${h}" rx="14" fill="#507467" opacity=".12"/><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="12" fill="${color}" stroke="#bacdc8"/><rect x="${x+10}" y="${y+10}" width="${w-20}" height="${h-20}" rx="7" fill="${roof}" stroke="#c8d8d5"/>${text(x+20,y+30,title,11,'#59716e')}</g>`;
  const tree=(x,y,r=13)=>`<g><ellipse cx="${x+3}" cy="${y+5}" rx="${r+3}" ry="${r}" fill="#638a72" opacity=".13"/><circle cx="${x}" cy="${y}" r="${r}" fill="#a8cdb0"/><circle cx="${x-3}" cy="${y-4}" r="${r*.7}" fill="#bfdcc4"/></g>`;
  let out='<g id="facility-scene" pointer-events="none"><rect x="-2400" y="-1400" width="6000" height="3500" fill="#edf3ef"/><rect x="28" y="24" width="1144" height="692" rx="26" fill="#e1ede2" stroke="#bfd1c5" stroke-width="2"/><rect x="54" y="45" width="1092" height="648" rx="18" fill="#f6f7ef" stroke="#d2ddd1"/>';
  out+='<path d="M140 275H1060V565H140Z" fill="none" stroke="#bcc6cc" stroke-width="72" stroke-linejoin="round"/><path d="M140 275H1060V565H140Z" fill="none" stroke="#d4dce1" stroke-width="60" stroke-linejoin="round"/><path d="M140 275H1060V565H140Z" fill="none" stroke="#f7fafc" stroke-width="2" stroke-dasharray="15 13" stroke-linejoin="round"/><path d="M600 275V565" stroke="#d4dce1" stroke-width="40"/><path d="M600 285V555" stroke="#f7fafc" stroke-width="2" stroke-dasharray="12 12"/>';
  out+=building(68,52,265,157,'OPERATIONS & DRONE CONTROL','#e9ece2','#f7f6ed');
  out+=building(408,40,262,178,'EDGE COMPUTE HUB','#dce8ed','#f1f6f8');
  out+=building(762,52,245,157,'LOGISTICS & CHARGING','#e7e3f1','#f6f3fa');
  out+=building(236,340,258,154,'ASSEMBLY CELL A','#e4e8f2','#f0f3fc');
  out+=building(723,340,244,154,'ASSEMBLY CELL B','#f0e4dc','#fbf3ed');
  for(let i=0;i<5;i++){out+=`<rect x="${98+i*39}" y="104" width="28" height="13" rx="2" fill="#c7d9df"/><rect x="${786+i*37}" y="111" width="26" height="15" rx="2" fill="#d2cde5"/>`;}
  for(let i=0;i<3;i++)out+=`<rect x="${431+i*68}" y="153" width="52" height="29" rx="3" fill="#93b6c8"/><path d="M${435+i*68} 160h44m-44 8h44" stroke="#d9e8ef" stroke-width="2"/>`;
  out+='<rect x="704" y="610" width="230" height="63" rx="7" fill="#dee6db" stroke="#c1cfc0"/>';
  for(let i=0;i<6;i++)out+=`<path d="M${718+i*34} 623v36" stroke="#f8faf8" stroke-width="2"/>`;
  out+='<circle cx="350" cy="643" r="32" fill="#dbe9dc" stroke="#b1cab7"/><circle cx="350" cy="643" r="23" fill="none" stroke="#9db5a4" stroke-width="2"/><path d="M339 630v26m22-26v26m-22-13h22" stroke="#91aa99" stroke-width="3"/>';
  out+=text(305,699,'DRONE LANDING PAD',10)+text(735,690,'DELIVERY / LOADING BAY',10)+text(515,703,'FACILITY SERVICE LOOP',10);
  out+='<path d="M270 295L480 310L640 390L550 490L270 450L185 370Z" stroke="#9cbabd" stroke-width="1.5" stroke-dasharray="5 7" fill="none" opacity=".45"/>';
  for(const [x,y]of [[90,325],[90,390],[90,455],[90,630],[150,654],[220,654],[1030,640],[1098,630],[1105,470],[1105,405],[1105,335],[356,102],[357,163],[706,102],[706,170]])out+=tree(x,y);
  out+='<g transform="translate(1085 72)"><circle r="24" fill="#f8fbf7" stroke="#cbd8cf"/><path d="M0-13L5 7L0 3L-5 7Z" fill="#719189"/>'+text(-4,-29,'N',10)+'</g>';
  out+=text(78,687,'ILLUSTRATIVE FACILITY · MOVEMENT DOES NOT ALTER LINK TIMING',9,'#8b9b90');
  return out+'</g>';
}

function acceptFacilityTime(x){
  if(x.time_us<facility.targetUs||state.starting){facility.fromUs=x.time_us;facility.timeUs=x.time_us;}else facility.fromUs=facility.timeUs;
  facility.targetUs=x.time_us;facility.receivedAt=performance.now();
}
function animateFacility(now,force=false){
  if(!state.snapshot||ground.key!==state.snapshot.config_hash)return;
  if(!force&&(state.view!=='simulation'||document.hidden||state.paused||state.error))return;
  const reduce=matchMedia('(prefers-reduced-motion:reduce)').matches;
  const fraction=force||reduce?1:Math.max(0,Math.min(1,(now-facility.receivedAt)/Math.max(34,packetDuration)));
  facility.timeUs=facility.fromUs+(facility.targetUs-facility.fromUs)*fraction;
  let changed=false;
  state.snapshot.devices.forEach((d,i)=>{if(facility.manual.has(d.device_id)||ground.gesture?.device===d.device_id||!$('device-motion').checked)return;
    const p=facilityDevicePosition(d,i,facility.timeUs);if(p){const old=ground.positions[d.device_id];if(Math.hypot(old.x-p.x,old.y-p.y)>.02){ground.positions[d.device_id]={x:p.x,y:p.y};changed=true;}const el=[...document.querySelectorAll('.ground-device')].find(e=>e.dataset.device===d.device_id);el?.querySelector('.mobile-vehicle')?.setAttribute('transform',`rotate(${p.heading})`);if(!reduce)el?.querySelectorAll('.drone-rotor').forEach(rotor=>rotor.setAttribute('transform',`rotate(${facility.timeUs/50%360} ${rotor.dataset.cx} ${rotor.dataset.cy})`));}});
  if(changed){moveGroundDevices();updateFacilityConnectionGeometry(state.snapshot);}
}
function updateFacilityConnectionGeometry(x){
  $('live-links')?.querySelectorAll('[data-transfer]').forEach(el=>{const a=ground.positions[el.dataset.source],b=ground.positions[el.dataset.target];if(!a||!b)return;const route=groundRoute(a,b,Number(el.dataset.lane)||0),p=route.point(Number(el.dataset.fraction));el.querySelector('path').setAttribute('d',route.path);const c=el.querySelector('circle');c.setAttribute('cx',p[0]);c.setAttribute('cy',p[1]);});
  const rec=$('recovery-links')?.querySelector('[data-recovery-task]');if(rec){const a=ground.positions[rec.dataset.source],b=ground.positions[rec.dataset.target];if(a&&b){rec.querySelector('path').setAttribute('d',groundRoute(a,b,55).path);const text=rec.querySelector('text');text.setAttribute('x',(a.x+b.x)/2);text.setAttribute('y',(a.y+b.y)/2+38);}}
}

function renderOtherWorkflows(x){
  const root=$('other-workflows');if(!root)return;const others=x.workflows.filter(w=>w.pipeline_id!==state.workflow),key=x.config_hash+'|'+state.device+'|'+state.workflow;
  if(root.dataset.key!==key){root.dataset.key=key;root.innerHTML=others.map(w=>{const layout=dependencyLayout(w,600,138,70);let svg='';w.dependency_edges.forEach(([a,b])=>{const [ax,ay]=layout.positions[a],[bx,by]=layout.positions[b];svg+=`<path data-edge-source="${esc(a)}" d="M${ax+138} ${ay+25}C${ax+158} ${ay+25},${bx-20} ${by+25},${bx} ${by+25}" fill="none" stroke="#cbd5e1" stroke-width="2" marker-end="url(#dependency-arrow)"/>`;});w.tasks.forEach(t=>{const [px,py]=layout.positions[t.task_id];svg+=`<g class="task-node" data-stage="${esc(t.task_id)}" role="button" tabindex="0"><title></title><rect class="task-box" x="${px}" y="${py}" width="138" height="52" rx="8" fill="white" stroke="#cbd5e1"/>${svgText(px+9,py+20,taskName(t.task_id),11,'#263753',600)}<text data-task-status x="${px+9}" y="${py+38}" font-size="10"/></g>`;});return `<article class="other-workflow ${w.tasks.length>3?'wide-workflow':''}" data-other-workflow="${esc(w.pipeline_id)}"><h3>${esc(w.pipeline_id)} <small>${w.tasks.length} task types · ${w.dependency_edges.length} dependencies</small></h3><div class="task-diagram"><svg role="group" aria-label="${esc(w.pipeline_id)} dependencies" viewBox="0 0 ${layout.width} ${Math.max(110,layout.height-30)}">${svg}</svg></div></article>`;}).join('');
    root.querySelectorAll('.task-node').forEach(node=>{const select=()=>{if(!node.dataset.task)return;state.workflow=node.closest('[data-other-workflow]').dataset.otherWorkflow;state.selectedTask=node.dataset.task;state.protectionTask=node.dataset.task;$('workflow').value=state.workflow;render(state.snapshot);};node.onclick=select;node.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select();}};});}
  root.querySelectorAll('[data-other-workflow]').forEach(panel=>{const id=panel.dataset.otherWorkflow,job=x.after.jobs.filter(j=>j.device===state.device&&j.workflow===id).at(-1),tasks=x.after.tasks.filter(t=>t.job===job?.id);
    panel.querySelectorAll('.task-node').forEach(node=>{const t=tasks.find(t=>t.name===node.dataset.stage),status=taskVisualState(t),c=statusColors[status]||'#94a3b8';node.dataset.task=t?.id||'';node.dataset.state=t?.state||'BLOCKED';node.querySelector('[data-task-status]').textContent=t?statusNames[status]:'Not released';node.querySelector('[data-task-status]').setAttribute('fill',c);node.querySelector('.task-box').setAttribute('fill',c+'0d');node.querySelector('.task-box').setAttribute('stroke',c+'80');node.querySelector('title').textContent=t?.id||node.dataset.stage;node.setAttribute('aria-label',node.dataset.stage+': '+(t?statusNames[status]:'Not released'));});
    panel.querySelectorAll('[data-edge-source]').forEach(edge=>{const committed=tasks.find(t=>t.name===edge.dataset.edgeSource)?.state==='COMMITTED';edge.dataset.predecessorCommitted=String(committed);edge.setAttribute('stroke',committed?'#10b981':'#b7c4d5');edge.setAttribute('stroke-dasharray',committed?'':'5 4');});});
}
