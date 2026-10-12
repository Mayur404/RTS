"""Validate facility travel, live task badges and all workflow dependencies."""
import argparse
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
        b=pw.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
        page=b.new_page(viewport={'width':1440,'height':1100},reduced_motion='reduce')
        page.add_init_script("const nativeRAF=window.requestAnimationFrame.bind(window);window.requestAnimationFrame=cb=>cb.name==='frame'?1:nativeRAF(cb)")
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(args.url)
        page.wait_for_function('researchState.snapshot&&!researchState.busy')
        page.locator('#pause').click()
        assert page.locator('#facility-scene').count()==1
        assert page.locator('#ground-zones').count()==0
        assert page.locator('#other-workflows [data-other-workflow]').count()==2
        before=page.evaluate('({...ground.positions.Device_1})')
        page.evaluate('async()=>{await advance(20000)}')
        after=page.evaluate('({...ground.positions.Device_1})')
        assert before!=after
        held=page.evaluate('researchState.snapshot.time_us')
        page.wait_for_timeout(150)
        assert page.evaluate('ground.positions.Device_1.x')==after['x']
        assert page.evaluate('researchState.snapshot.time_us')==held
        # Resource badges trace to exact task owners in the accepted snapshot.
        x=page.evaluate('researchState.snapshot')
        badges=page.locator('[data-owner-task]').evaluate_all('els=>els.map(e=>({task:e.dataset.ownerTask,text:e.textContent}))')
        for badge in badges:
            if badge['task']:assert any(t['id']==badge['task'] for t in x['after']['tasks'])
        for w in x['workflows']:
            panel=page.locator('#task-graph') if w['pipeline_id']==page.locator('#workflow').input_value() else page.locator('[data-other-workflow="'+w['pipeline_id']+'"]')
            assert panel.locator('[data-stage]').count()==len(w['tasks'])
            assert panel.locator('[data-edge-source]').count()==len(w['dependency_edges'])
        # An actual task from the control DAG opens the same task in the inspector.
        control=page.locator('[data-other-workflow="control"] [data-task]').first
        task=control.get_attribute('data-task');control.click()
        assert page.locator('#workflow').input_value()=='control'
        assert page.evaluate('researchState.selectedTask')==task
        assert task in page.locator('#task-detail').inner_text()
        # Movement toggle holds geometry through real simulation steps.
        page.locator('#device-motion').uncheck()
        frozen=page.evaluate('({...ground.positions.Device_1})')
        page.evaluate('async()=>{await advance(10000)}')
        assert page.evaluate('({...ground.positions.Device_1})')==frozen
        page.locator('#device-motion').check()
        # Dragging a rover overrides only that device's illustrative route.
        face=page.locator('[data-device="Device_3"] .device-face');face.scroll_into_view_if_needed();box=face.bounding_box()
        page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2);page.mouse.down();page.mouse.move(box['x']+box['width']/2+45,box['y']+box['height']/2-25,steps=6);page.mouse.up()
        dragged=page.evaluate('({...ground.positions.Device_3})')
        assert page.evaluate('facility.manual.has("Device_3")')
        page.evaluate('async()=>{await advance(10000)}')
        assert page.evaluate('({...ground.positions.Device_3})')==dragged
        page.locator('#reset-nodes').click();assert not page.evaluate('facility.manual.has("Device_3")')
        page.locator('#workflow').select_option('autonomy')
        assert page.evaluate('researchState.selectedTask') is None
        assert page.evaluate('researchState.protectionTask') is None
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(root/'facility-desktop.png'),full_page=True)
        for width in [320,390,768,1024,1440]:
            page.set_viewport_size({'width':width,'height':900})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
        page.set_viewport_size({'width':390,'height':900});page.locator('#focus-device').click();page.screenshot(path=str(root/'facility-mobile.png'),full_page=True)
        assert not errors,errors
        x=page.evaluate('researchState.snapshot')
        (root/'result.json').write_text(json.dumps({'status':'passed','session_id':x['session_id'],'config_hash':x['config_hash'],'time_us':x['time_us'],'badges':badges,'workflows':[w['pipeline_id'] for w in x['workflows']],'browser_errors':errors},indent=2),encoding='utf-8')
        b.close()
    print('Facility scene, travel, task badges and dependency checks passed.')


if __name__=='__main__':main()
