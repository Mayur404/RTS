"""Browser acceptance checks for the two-view UI against actual session records."""
import argparse
import hashlib
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:8000')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    root=Path(args.output)
    if (root/'result.json').exists():parser.error('use a fresh output directory')
    root.mkdir(parents=True,exist_ok=True)
    errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        page.add_init_script("const nativeRAF=window.requestAnimationFrame.bind(window);window.requestAnimationFrame=cb=>cb.name==='frame'?1:nativeRAF(cb)")
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(args.url)
        page.wait_for_function('researchState.snapshot && !researchState.busy')
        assert page.get_by_role('tab').all_text_contents()==['Simulation','Results']
        page.locator('#pause').click()
        page.locator('#step-once').click()
        page.wait_for_function('!researchState.busy')
        assert page.evaluate('researchState.snapshot.time_us')==1000
        # A real connection must be backed by an in-flight transfer.
        page.evaluate('async()=>{for(let i=0;i<500&&!liveTransfers(researchState.snapshot).length;i++)await advance(1000)}')
        x=page.evaluate('researchState.snapshot')
        assert page.locator('[data-transfer]').count()>0
        for t in page.locator('[data-transfer]').evaluate_all('els=>els.map(e=>({source:e.dataset.source,target:e.dataset.target,f:Number(e.dataset.fraction)}))'):
            assert 0<=t['f']<=1
            assert any(v['source']==t['source'] and v['target']==t['target'] and v['start_us']<=x['time_us']<v['end_us'] for v in x['after']['transfers'])
        for node in page.locator('[data-task]').evaluate_all('els=>els.map(e=>({id:e.dataset.task,state:e.dataset.state}))'):
            if node['id']:assert next(t['state'] for t in x['after']['tasks'] if t['id']==node['id'])==node['state']
        # Rendering another snapshot retains existing task elements and their focus.
        page.evaluate('window.heldNode=document.querySelector(".task-node");heldNode.focus()')
        page.evaluate('async()=>{await advance(1000)}')
        assert page.evaluate('heldNode===document.querySelector(".task-node")&&document.activeElement===heldNode')
        # Ordinary motion interpolates accepted packet positions; pause stops it.
        page.emulate_media(reduced_motion='no-preference')
        animated=page.evaluate('async()=>{researchState.paused=false;let found=false;for(let i=0;i<30&&!found;i++){await advance(250);found=document.getAnimations().some(a=>a.effect?.target?.tagName==="circle")}return found}')
        assert animated
        page.locator('#pause').click()
        assert not page.evaluate('document.getAnimations().some(a=>a.effect?.target?.tagName==="circle")')
        page.emulate_media(reduced_motion='reduce')
        before=page.evaluate('researchState.snapshot.time_us')
        page.locator('[data-task]').first.click()
        assert page.locator('#task-inspector').is_visible()
        page.locator('#tab-simulation').focus();page.keyboard.press('End')
        assert page.locator('#tab-results').get_attribute('aria-selected')=='true'
        page.keyboard.press('Home')
        assert page.evaluate('researchState.snapshot.time_us')==before
        page.screenshot(path=str(root/'simulation-desktop.png'),full_page=True)
        for width in [320,390,768,1024,1440]:
            page.set_viewport_size({'width':width,'height':900})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
            assert page.get_by_role('tab').count()==2
            assert page.locator('[data-device]').count()==len(x['devices'])
        page.set_viewport_size({'width':390,'height':900})
        page.screenshot(path=str(root/'simulation-mobile.png'),full_page=True)
        # Fail a real step and check that no result is invented on failure.
        page.route('**/api/research/sessions/*/step',lambda route:route.fulfill(status=503,content_type='application/json',body='{"detail":"acceptance-check outage"}'))
        page.locator('#step-once').click();page.wait_for_function('!researchState.busy')
        assert page.locator('#error').is_visible()
        assert page.evaluate('researchState.snapshot.time_us')==before
        assert page.evaluate('researchState.paused')
        page.unroute('**/api/research/sessions/*/step')
        page.locator('#pause').click();page.locator('#pause').click()
        # Complete the same run and reconcile all visible results and downloads.
        page.evaluate('async()=>{while(researchState.snapshot.phase!=="COMPLETE")await advance(100000)}')
        x=page.evaluate('researchState.snapshot')
        page.locator('#tab-results').click()
        for name,key in [('before','before'),('after','after')]:
            assert page.locator('#'+name).inner_text()==f"{x[key]['metrics']['job_dmr_pct']:.2f}%"
        counts=page.evaluate('pairedJobCounts(researchState.snapshot)')
        assert sum(counts.values())==x['after']['metrics']['released_jobs']
        assert counts['pending']==0
        for key,count in counts.items():assert int(page.locator('[data-paired-category='+key+']').get_attribute('data-paired-count'))==count
        identities=[]
        for policy,urls in x['artifact_urls'].items():
            manifest=page.request.get(args.url+urls['manifest.json']).json()
            raw=page.request.get(args.url+urls['events.jsonl']).body()
            digest=hashlib.sha256(raw).hexdigest()
            assert manifest['event_sha256']==digest
            metrics=page.request.get(args.url+urls['metrics.json']).json()
            assert metrics['job_dmr_pct']==x['after' if policy=='protected' else 'before']['metrics']['job_dmr_pct']
            identities.append({'policy':policy,'trace_sha256':digest,'manifest':manifest})
        page.set_viewport_size({'width':1440,'height':1000})
        page.screenshot(path=str(root/'results-desktop.png'),full_page=True)
        # Changing workflow, zoom or tab never advances the simulator.
        held=x['time_us'];page.locator('#tab-simulation').click();page.locator('#workflow').select_option('control');page.locator('#zoom-in').click();page.locator('#zoom-reset').click()
        assert page.evaluate('researchState.snapshot.time_us')==held
        # Each built-in scenario can replace a session without keeping stale tasks.
        families=[]
        for family in ['nominal','bursty','thermal','unreliable']:
            old=page.evaluate('researchState.snapshot.session_id')
            page.locator('#scenario').select_option(family)
            page.wait_for_function('(old)=>researchState.snapshot.session_id!==old&&!researchState.busy',arg=old)
            assert page.evaluate('researchState.snapshot.family')==family
            page.locator('#pause').click();awaited=page.evaluate('async()=>{await advance(100000);return researchState.snapshot.time_us}')
            assert awaited==100000
            families.append(family)
        assert not errors,errors
        (root/'result.json').write_text(json.dumps({'status':'passed','session_id':x['session_id'],'config_hash':x['config_hash'],'families':families,'metrics':{'before':x['before']['metrics'],'after':x['after']['metrics']},'paired_counts':counts,'artifacts':identities,'browser_errors':errors},indent=2),encoding='utf-8')
        browser.close()
    print('Two-view simulation browser checks passed.')


if __name__=='__main__':main()
