"""Ground-map interaction and recovery evidence checks in real Chrome."""
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
        context=b.new_context(viewport={'width':1440,'height':1000},has_touch=True,reduced_motion='reduce')
        page=context.new_page()
        page.add_init_script("const nativeRAF=window.requestAnimationFrame.bind(window);window.requestAnimationFrame=cb=>cb.name==='frame'?1:nativeRAF(cb)")
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(args.url)
        page.wait_for_function('researchState.snapshot&&!researchState.busy')
        assert page.locator('[data-device]').count()==6
        page.locator('#pause').click()
        page.evaluate('async()=>{await advance(20000)}')
        held=page.evaluate('researchState.snapshot.time_us')
        def check_usage():
            x=page.evaluate('researchState.snapshot')
            for d in page.locator('.ground-device').evaluate_all('els=>els.map(e=>({id:e.dataset.device,cpu:Number(e.dataset.cpuUsage),gpu:Number(e.dataset.gpuUsage),sample:Number(e.dataset.sampleUs)}))'):
                sample=x['after']['resources'][d['id']]
                assert abs(d['cpu']-sample['cpu_ppm']/10000)<1e-9
                assert abs(d['gpu']-sample['gpu_ppm']/10000)<1e-9
                assert d['sample']==sample['at_us']
        check_usage()
        # Device clicks select the task graph; dragging changes only display geometry.
        page.locator('[data-device="Device_2"] .device-face').click()
        assert page.locator('#inspect-device').input_value()=='Device_2'
        old=page.evaluate('({...ground.positions.Device_2})')
        face=page.locator('[data-device="Device_2"] .device-face').bounding_box()
        page.mouse.move(face['x']+face['width']/2,face['y']+face['height']/2);page.mouse.down();page.mouse.move(face['x']+face['width']/2+70,face['y']+face['height']/2+40,steps=8);page.mouse.up()
        changed=page.evaluate('({...ground.positions.Device_2})')
        assert changed['x']>old['x']+50 and changed['y']>old['y']+20
        page.evaluate('async()=>{await advance(1000)}')
        assert page.evaluate('ground.positions.Device_2.x')==changed['x']
        held+=1000
        # Pan, wheel zoom, fit and keyboard motion do not advance time.
        page.locator('#zoom-in').click();assert page.evaluate('ground.camera.scale')>1
        page.locator('#zoom-out').click();page.locator('#zoom-reset').click()
        bounds=page.locator('#simulation-canvas').bounding_box()
        page.mouse.move(bounds['x']+20,bounds['y']+20);page.mouse.down();page.mouse.move(bounds['x']+65,bounds['y']+50,steps=5);page.mouse.up()
        assert page.evaluate('Math.abs(ground.camera.x)>20')
        page.mouse.wheel(0,-180);assert page.evaluate('ground.camera.scale')>1
        page.locator('#zoom-reset').click();assert page.evaluate('ground.camera.scale')==1
        page.locator('[data-device="Device_2"]').focus();page.keyboard.press('ArrowRight')
        assert page.evaluate('ground.positions.Device_2.x')==changed['x']+10
        assert page.evaluate('researchState.snapshot.time_us')==held
        # Real touch pinch changes the camera scale.
        cdp=context.new_cdp_session(page)
        bounds=page.locator('#simulation-canvas').bounding_box();cx=bounds['x']+bounds['width']/2;cy=bounds['y']+bounds['height']/2
        for kind,spread in [('touchStart',35),('touchMove',70)]:
            cdp.send('Input.dispatchTouchEvent',{'type':kind,'touchPoints':[{'x':cx-spread,'y':cy,'id':1},{'x':cx+spread,'y':cy,'id':2}]})
        cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
        assert page.evaluate('ground.camera.scale')>1.5
        page.locator('#zoom-reset').click();page.locator('#reset-nodes').click()
        assert page.evaluate('ground.positions.Device_2.x')==old['x']
        # Find an actual watchdog abort, pin it, and reconcile every timeline timestamp.
        page.locator('#slow-motion').click()
        assert page.locator('#playback-speed').input_value()=='0.05'
        assert page.locator('#pause-recovery').is_checked()
        found=page.evaluate('async()=>{researchState.paused=false;for(let i=0;i<150&&researchState.snapshot.phase!=="COMPLETE";i++){await advance(10000);if(researchState.paused&&researchState.protectionTask)return true}return false}')
        assert found,'No recorded watchdog abort occurred in this actual scenario'
        assert page.evaluate('researchState.paused')
        record=page.evaluate('protectionRecord(researchState.snapshot,researchState.protectionTask,researchState.protectionEvents)')
        assert record['abort']
        assert page.locator('[data-recovery-task]').count()==1
        for key,label,time in record['steps']:
            node=page.locator('[data-protection-milestone="'+key+'"]')
            assert node.get_attribute('data-event-us')==('' if time is None else str(time))
        page.locator('#pause-recovery').uncheck()
        # Step through the admitted exit to its actual commit, without making up a result.
        page.evaluate('async()=>{for(let i=0;i<80;i++){const t=researchState.snapshot.after.tasks.find(t=>t.id===researchState.protectionTask);if(["COMMITTED","MISSED","SKIPPED"].includes(t.state))break;await advance(500)}}')
        record=page.evaluate('protectionRecord(researchState.snapshot,researchState.protectionTask,researchState.protectionEvents)')
        assert next(t[2] for t in record['steps'] if t[0]=='EARLY_EXIT') is not None
        assert record['task']['state'] in ['COMMITTED','MISSED','SKIPPED']
        assert page.locator('[data-recovery-task]').count()==0,'Completed recovery left a live map arrow'
        assert page.locator('[data-protection-milestone="WATCHDOG_ABORT"]').get_attribute('data-observed')=='true'
        check_usage()
        page.screenshot(path=str(root/'watchdog-desktop.png'),full_page=True)
        recovery_task=record['task']['id']
        page.evaluate('async()=>{while(researchState.snapshot.phase!=="COMPLETE")await advance(100000)}')
        assert page.locator('[data-transfer]').count()==0
        assert page.locator('[data-recovery-task]').count()==0
        assert page.locator('#live-count').inner_text()=='0'
        for width in [320,390,768,1024,1440]:
            page.set_viewport_size({'width':width,'height':900})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
            assert page.get_by_role('tab').count()==2
        page.set_viewport_size({'width':390,'height':900});page.locator('#focus-device').click();assert page.evaluate('ground.camera.scale')==3;page.screenshot(path=str(root/'ground-mobile.png'),full_page=True)
        page.set_viewport_size({'width':1440,'height':1000})
        # All exposed task mixes and the largest fleet compile and render real runs.
        cases=[]
        for control,value in [('device-count','8'),('task-mix','autonomy'),('task-mix','control'),('task-mix','telemetry'),('task-mix','mixed')]:
            previous=page.evaluate('researchState.snapshot.session_id');page.locator('#'+control).select_option(value)
            page.wait_for_function('(old)=>researchState.snapshot.session_id!==old&&!researchState.busy',arg=previous)
            page.locator('#pause').click();page.evaluate('async()=>{await advance(10000)}')
            assert len(page.evaluate('researchState.snapshot.devices'))==8
            if control=='task-mix' and value!='mixed':assert page.evaluate('researchState.snapshot.workflows.map(w=>w.pipeline_id)')==[value]
            cases.append({'control':control,'value':value,'session_id':page.evaluate('researchState.snapshot.session_id')})
        previous=page.evaluate('researchState.snapshot.session_id');page.locator('#task-rate').focus();page.keyboard.press('End')
        page.wait_for_function('(old)=>researchState.snapshot.session_id!==old&&!researchState.busy',arg=previous)
        assert page.locator('#task-rate-label').inner_text()=='150%'
        assert page.evaluate('researchState.snapshot.workflows.find(w=>w.pipeline_id==="control").period_us')==13333
        page.screenshot(path=str(root/'eight-devices.png'),full_page=True)
        assert not errors,errors
        x=page.evaluate('researchState.snapshot')
        (root/'result.json').write_text(json.dumps({'status':'passed','session_id':x['session_id'],'config_hash':x['config_hash'],'recovery_task':recovery_task,'recovery_record':record,'configuration_cases':cases,'browser_errors':errors},indent=2),encoding='utf-8')
        b.close()
    print('Ground map, usage, gestures, configuration and recovery checks passed.')


if __name__=='__main__':main()
