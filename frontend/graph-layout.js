/* Deterministic topological layout; positions describe configuration, not evidence. */
function dependencyLayout(workflow, width=1000, nodeWidth=138, rowGap=90) {
  const ids=workflow.tasks.map(t=>t.task_id), levels=new Map(ids.map(id=>[id,0]));
  const incoming=new Map(ids.map(id=>[id,0])), children=new Map(ids.map(id=>[id,[]]));
  for(const [a,b] of workflow.dependency_edges){if(!children.has(a)||!incoming.has(b))throw Error('Unknown dependency task');children.get(a).push(b);incoming.set(b,incoming.get(b)+1);}
  const ready=ids.filter(id=>!incoming.get(id)), ordered=[];
  while(ready.length){const id=ready.shift();ordered.push(id);for(const child of children.get(id)){levels.set(child,Math.max(levels.get(child),levels.get(id)+1));incoming.set(child,incoming.get(child)-1);if(!incoming.get(child))ready.push(child);}}
  if(ordered.length!==ids.length)throw Error('Dependencies must form an acyclic graph');
  const depth=Math.max(...levels.values()), groups=Array.from({length:depth+1},()=>[]);
  for(const id of ids)groups[levels.get(id)].push(id);
  const height=Math.max(180,Math.max(...groups.map(g=>g.length))*rowGap+65), positions={};
  const actualWidth=Math.max(width,(depth+1)*(nodeWidth+38)+35);
  groups.forEach((group,l)=>group.forEach((id,i)=>positions[id]=[24+(depth?l*(actualWidth-nodeWidth-48)/depth:(actualWidth-nodeWidth-48)/2),35+(i+(Math.max(...groups.map(g=>g.length))-group.length)/2)*rowGap]));
  return {positions,width:actualWidth,height};
}
