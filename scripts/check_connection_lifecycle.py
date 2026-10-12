"""Check actual packet lifecycle and stable SVG nodes in the running simulator."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:8000/?family=bursty')
    parser.add_argument('--output',required=True)
    args=parser.parse_args();root=Path(args.output)
    if (root/'result.json').exists():parser.error('use a fresh output directory')
    root.mkdir(parents=True,exist_ok=True);errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.add_init_script("const raf=window.requestAnimationFrame.bind(window);window.requestAnimationFrame=cb=>cb.name==='frame'?1:raf(cb)")
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(args.url);page.wait_for_function('researchState.snapshot&&!researchState.busy')
        page.locator('#pause').click()
        transfer=page.evaluate('''async()=>{for(let i=0;i<200;i++){
          const t=liveTransfers(researchState.snapshot).find(t=>t.end_us-researchState.snapshot.time_us>2000);
          if(t)return t;await advance(1000);
        }return null}''')
        assert transfer,'No actual packet observed'
        # Redraws preserve the SVG element, rather than restarting its animation.
        out=page.evaluate('''(id)=>{
          window.packetNode=[...document.querySelectorAll('[data-transfer]')].find(e=>e.dataset.transfer===id);const key=packetNode.dataset.transfer;
          renderGroundConnections(researchState.snapshot);renderGroundConnections(researchState.snapshot);
          return {stable:[...document.querySelectorAll('[data-transfer]')].some(e=>e===packetNode&&e.dataset.transfer===key),
                  drawn:document.querySelectorAll('[data-transfer]').length,actual:liveTransfers(researchState.snapshot).length};
        }''',transfer['id'])
        assert out['stable'] and out['drawn']==out['actual']
        # An unavailable resource sample must clear a previous owner, not retain it.
        cleared=page.evaluate('''()=>{
          const missing=structuredClone(researchState.snapshot);missing.after.resources={};renderGroundMap(missing);
          const cleared=[...document.querySelectorAll('[data-live-cpu-task],[data-live-gpu-task]')]
            .every(el=>el.dataset.ownerTask===''&&el.textContent.includes('No sample'));
          renderGroundMap(researchState.snapshot);return cleared;
        }''')
        assert cleared
        # A new accepted snapshot starts interpolation once. A same-snapshot render preserves it.
        animation=page.evaluate('''async()=>{
          researchState.paused=false;await advance(100);
          const circle=packetNode.querySelector('circle'),before=circle.getAnimations()[0];
          renderGroundConnections(researchState.snapshot);
          const preserved=Boolean(before)&&circle.getAnimations()[0]===before;
          researchState.paused=true;stopMotion();renderGroundConnections(researchState.snapshot);
          return {preserved,pausedAnimations:circle.getAnimations().length};
        }''')
        assert animation=={'preserved':True,'pausedAnimations':0}
        page.evaluate('(end)=>advance(end-researchState.snapshot.time_us)',transfer['end_us'])
        assert not page.evaluate('(id)=>[...document.querySelectorAll("[data-transfer]")].some(e=>e.dataset.transfer===id)',transfer['id'])
        assert not page.evaluate('(id)=>liveTransfers(researchState.snapshot).some(t=>t.id===id)',transfer['id'])
        returned=page.evaluate('''async()=>{for(let i=0;i<400&&researchState.snapshot.phase!=='COMPLETE';i++){
          const t=liveTransfers(researchState.snapshot).find(t=>t.phase==='result');if(t)return t;await advance(1000);
        }return null}''')
        assert returned,'No actual remote result transfer observed; use the busy-device scenario (?family=bursty)'
        node=page.locator('[data-transfer="'+returned['id']+'"]')
        assert node.locator('.transfer-label text').text_content()=='Result returning'
        page.evaluate('(task)=>{researchState.protectionTask=task;render(researchState.snapshot)}',returned['task'])
        assert page.locator('[data-protection-milestone="RESULT_SENT"]').get_attribute('data-observed')=='true'
        assert page.locator('[data-protection-milestone="RESULT_ARRIVED"]').get_attribute('data-observed')=='false'
        page.evaluate('(end)=>advance(end-researchState.snapshot.time_us)',returned['end_us'])
        record=page.evaluate('protectionRecord(researchState.snapshot,researchState.protectionTask,researchState.protectionEvents)')
        actual=[e for e in record['handoff']['events'] if e['event_type']=='TX_END' and e['payload']['phase']=='result']
        assert actual
        assert page.locator('[data-protection-milestone="RESULT_ARRIVED"]').get_attribute('data-event-us')==str(actual[0]['timestamp_us'])
        page.evaluate('async()=>{while(researchState.snapshot.phase!=="COMPLETE")await advance(100000)}')
        assert page.locator('[data-transfer]').count()==0
        assert page.locator('[data-recovery-task]').count()==0
        assert page.locator('#live-count').inner_text()=='0'
        assert not errors,errors
        x=page.evaluate('researchState.snapshot')
        page.screenshot(path=str(root/'completed-map.png'),full_page=True)
        (root/'result.json').write_text(json.dumps({'status':'PASS','session_id':x['session_id'],
            'config_hash':x['config_hash'],'observed_transfer':transfer,'returned_result':returned,'stable_nodes':out,
            'animation':animation,'browser_errors':errors},indent=2),encoding='utf-8')
        browser.close()
    print('Live packet lifecycle, stable animation and completed-map checks passed.')


if __name__=='__main__':main()
