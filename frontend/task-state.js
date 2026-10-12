/* One state palette across the DAG, atlas and inspection. Terminal failure wins
   over execution mode: an early exit can still miss its deadline. */
const visualPalette={BLOCKED:'#c6d2df',DECIDING:'#818bb8',QUEUED:'#818bb8',RUNNING:'#3977c5',OFFLOADED:'#7065c5',COMMITTED:'#087f78',MISSED:'#c05252',SKIPPED:'#919dac',DEGRADED:'#b57b17'};
function taskVisualState(task){
  const status=task?.state||'BLOCKED';
  if(status==='MISSED'||status==='SKIPPED')return status;
  return task?.degraded?'DEGRADED':status;
}
function taskColor(task){return visualPalette[taskVisualState(task)]||visualPalette.BLOCKED;}

function gpuLayerProgress(attempt,count=4){
  // Layer ordinals on start events and resource samples use different bases.
  // Delivered integer service is authoritative for every execution attempt.
  const total=attempt?.total_work_us,work=attempt?.work_done_us;
  if(!(total>0)||work==null||attempt.degraded)return Array(count).fill(0);
  return Array.from({length:count},(_,i)=>{
    const start=Math.ceil(total*i/count),end=Math.ceil(total*(i+1)/count);
    return end===start?(work>=end?1:0):Math.max(0,Math.min(1,(work-start)/(end-start)));
  });
}
