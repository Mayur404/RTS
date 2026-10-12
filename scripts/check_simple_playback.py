"""Check the real animation-frame playback loop and pause during live requests."""
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
        browser=pw.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(args.url)
        page.wait_for_function('researchState.snapshot?.time_us>3000',polling=50)
        page.locator('#pause').click()
        page.wait_for_function('researchState.paused&&!researchState.busy',polling=50)
        held=page.evaluate('researchState.snapshot.time_us')
        held_positions=page.evaluate('JSON.stringify(ground.positions)')
        page.wait_for_timeout(300)
        assert page.evaluate('researchState.snapshot.time_us')==held
        assert page.evaluate('JSON.stringify(ground.positions)')==held_positions
        assert not page.evaluate('document.getAnimations().some(a=>a.effect?.target?.tagName==="circle")')
        page.locator('#step-once').click()
        page.wait_for_function('!researchState.busy',polling=50)
        assert page.evaluate('researchState.snapshot.time_us')==held+1000
        page.locator('#playback-speed').focus()
        page.keyboard.press('End')
        page.locator('#pause').click()
        page.wait_for_function('(t)=>researchState.snapshot.time_us>t',arg=held+1000,polling=50)
        page.wait_for_function('(held)=>JSON.stringify(ground.positions)!==held',arg=held_positions,polling=50)
        page.locator('#tab-results').click()
        page.wait_for_function('Number(document.getElementById("run-progress").getAttribute("aria-valuenow"))>0',polling=50)
        page.locator('#pause').click()
        page.wait_for_function('researchState.paused&&!researchState.busy',polling=50)
        x=page.evaluate('researchState.snapshot')
        assert page.locator('#after').inner_text()==f"{x['after']['metrics']['job_dmr_pct']:.2f}%"
        page.locator('#tab-simulation').click()
        page.screenshot(path=str(root/'automatic-playback.png'),full_page=True)
        assert not errors,errors
        (root/'result.json').write_text(json.dumps({'status':'passed','session_id':x['session_id'],'config_hash':x['config_hash'],'paused_us':held,'final_paused_us':x['time_us'],'browser_errors':errors},indent=2),encoding='utf-8')
        browser.close()
    print('Automatic playback and settled pause checks passed.')


if __name__=='__main__':main()
