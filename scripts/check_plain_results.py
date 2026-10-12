"""User-facing final deadline and recovery counts must match actual raw records."""
import argparse
from collections import Counter
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8000');parser.add_argument('--output',required=True)
    args=parser.parse_args();root=Path(args.output)
    if (root/'result.json').exists():parser.error('use a fresh output directory')
    root.mkdir(parents=True,exist_ok=True);errors=[]
    with sync_playwright() as pw:
        b=pw.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
        page=b.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce')
        page.add_init_script("const nativeRAF=window.requestAnimationFrame.bind(window);window.requestAnimationFrame=cb=>cb.name==='frame'?1:nativeRAF(cb)")
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(args.url);page.wait_for_function('researchState.snapshot&&!researchState.busy');page.locator('#pause').click();page.locator('#tab-results').click()
        assert page.locator('#plain-results').get_attribute('data-final')=='false'
        assert 'not final' in page.locator('#plain-results').inner_text()
        assert not page.locator('#results-check').is_visible()
        page.evaluate('async()=>{while(researchState.snapshot.phase!=="COMPLETE")await advance(100000)}')
        x=page.evaluate('researchState.snapshot');s=page.evaluate('deriveResultSummary(researchState.snapshot)')
        assert not s['issues']
        assert page.locator('#plain-results').get_attribute('data-final')=='true'
        raw=[]
        for policy,urls in x['artifact_urls'].items():
            trace=[json.loads(line) for line in page.request.get(args.url+urls['events.jsonl']).text().splitlines()]
            if policy=='protected':raw=trace
        counters=Counter(e['event_type'] for e in raw)
        admitted={e['task_id'] for e in raw if e['event_type']=='FALLBACK_ADMITTED'}
        committed={e['task_id'] for e in raw if e['event_type']=='TASK_COMMIT'}
        expected={'fallback_tasks':len(admitted),'fallback_finished':len(admitted&committed),'watchdog_aborts':counters['WATCHDOG_ABORT'],'early_exits':counters['EARLY_EXIT'],'rescued':s['paired']['rescued'],'regressed':s['paired']['regressed']}
        for key,n in expected.items():assert int(page.locator('[data-result-count="'+key+'"]').get_attribute('data-count'))==n
        assert s['net']==x['before']['metrics']['missed_jobs']-x['after']['metrics']['missed_jobs']
        # An inconsistent record must show a review message, never a benefit claim.
        page.evaluate('()=>{const bad=structuredClone(researchState.snapshot);bad.after.jobs[0].id="missing-paired-identity";renderPlainResults(bad)}')
        assert page.locator('#results-check').is_visible()
        assert page.locator('#plain-results').get_attribute('data-tone')=='review'
        page.evaluate('renderResults(researchState.snapshot)')
        assert not page.locator('#results-check').is_visible()
        assert page.locator('[data-result-device]').count()==len(x['devices'])
        assert '1.500 s' in page.locator('#run-times').inner_text()
        assert '0.30 s' in page.locator('#run-times').inner_text()
        page.locator('#changed-workflows').locator('..').locator('summary').click()
        page.screenshot(path=str(root/'deadline-results-desktop.png'),full_page=True)
        for width in [320,390,768,1024,1440]:
            page.set_viewport_size({'width':width,'height':900});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
        page.set_viewport_size({'width':390,'height':900});page.screenshot(path=str(root/'deadline-results-mobile.png'),full_page=True)
        assert not errors,errors
        (root/'result.json').write_text(json.dumps({'status':'PASS','session_id':x['session_id'],'configuration_hash':x['config_hash'],'summary':s,'raw_counts':expected,'browser_errors':errors},indent=2),encoding='utf-8')
        b.close()
    print('Plain final results reconcile with canonical raw records.')


if __name__=='__main__':main()
