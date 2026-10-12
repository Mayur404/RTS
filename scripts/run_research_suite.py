"""Run actual paired layered experiments and bootstrap per-seed paired effects."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import random
import sys
from dataclasses import replace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rts_predictive.api.research import PairedResearchSession
from rts_predictive.domain.research import default_research_config


def bootstrap(values,seed=91):
    rng=random.Random(seed)
    samples=sorted(sum(rng.choices(values,k=len(values)))/len(values) for _ in range(5000))
    return [samples[124],samples[4874]] if len(values)>1 else None


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--seeds',type=int,default=30)
    p.add_argument('--first-seed',type=int,default=1000)
    p.add_argument('--families',nargs='+',default=['bursty'],choices=['nominal','bursty','thermal','unreliable'])
    p.add_argument('--release-us',type=int,default=1200000)
    p.add_argument('--output',default='.validation/layered-suite')
    p.add_argument('--disable',nargs='*',default=[],choices=['watchdog','fl','offload','fallback'])
    p.add_argument('--baseline',default='edf',choices=['edf','fifo','rm','always_offload','reactive','predictive_no_fallback'])
    p.add_argument('--inference-us',type=int,default=None,help='Simulated CPU work per GNN call; not a measured WCET')
    p.add_argument('--base-link-us',type=int,default=None,help='Configured propagation delay per transfer')
    a=p.parse_args()
    if a.seeds<1:p.error('at least one seed required')
    # Keep evaluation disjoint from the GNN dataset groups.
    if any(4100<=s<=4301 for s in range(a.first_seed,a.first_seed+a.seeds)):
        p.error('evaluation seeds overlap the reserved GNN training/validation/test range')
    root=Path(a.output);root.mkdir(parents=True,exist_ok=True)
    rows=[]
    for family in a.families:
        for seed in range(a.first_seed,a.first_seed+a.seeds):
            configuration=default_research_config(seed,family,a.release_us)
            overrides={}
            if a.inference_us is not None:overrides['inference_cost_us']=a.inference_us
            if a.base_link_us is not None:overrides['base_link_us']=a.base_link_us
            configuration=replace(configuration,**overrides)
            session=PairedResearchSession(configuration,root,baseline=a.baseline,
                                          **{'enable_'+f:False for f in a.disable})
            x=session.step(session.config.end_us)
            rows.append({'family':family,'seed':seed,'pair_id':session.id,**x['comparison'],
                         'before':x['before']['metrics'],'after':x['after']['metrics'],
                         'manifest_files':{policy:{'path':str((session.root/policy/'manifest.json').resolve()),
                           'sha256':hashlib.sha256((session.root/policy/'manifest.json').read_bytes()).hexdigest()}
                                           for policy in [a.baseline,'protected']}})
            print(f"{family} seed {seed}: {x['comparison']['before_pct']:.3f}% -> {x['comparison']['after_pct']:.3f}%",flush=True)
    groups={}
    for family in a.families:
        rr=[r for r in rows if r['family']==family]
        effects=[r['change_pp'] for r in rr]
        groups[family]={'paired_seeds':len(rr),'mean_before_pct':sum(r['before_pct'] for r in rr)/len(rr),
                        'mean_after_pct':sum(r['after_pct'] for r in rr)/len(rr),
                        'mean_change_pp':sum(effects)/len(rr),'paired_bootstrap_95_ci_pp':bootstrap(effects),
                        'bootstrap_replicates':5000,'bootstrap_seed':91,
                        'regressed_seeds':sum(v<0 for v in effects),'evidence':'SIMULATED'}
    output={'schema_version':'research-suite/1.0','primary_endpoint':'end_to_end_job_deadline_miss_ratio',
            'release_end_us':a.release_us,'baseline':a.baseline,'configuration_overrides':overrides,
            'disabled_features':a.disable,'groups':groups,'pairs':rows}
    (root/'aggregate.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
    with (root/'paired.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=['family','seed','pair_id','before_pct','after_pct','change_pp','relative_reduction_pct'])
        writer.writeheader();writer.writerows({k:r[k] for k in writer.fieldnames} for r in rows)
    # Publication plots only consume these actual paired outcomes.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,len(groups),figsize=(5*len(groups),4),squeeze=False)
    for ax,(family,g) in zip(axes[0],groups.items()):
        rr=[r for r in rows if r['family']==family]
        for r in rr:ax.plot([0,1],[r['before_pct'],r['after_pct']],color='#aec4d0',alpha=.65,lw=1)
        ax.scatter([0,1],[g['mean_before_pct'],g['mean_after_pct']],color=['#435873','#087f78'],s=55,zorder=3)
        ax.set(xticks=[0,1],xticklabels=[a.baseline,'Protected'],ylabel='End-to-end job misses (%)',title=f'{family} · {len(rr)} paired seeds')
        ax.spines[['top','right']].set_visible(False)
    fig.tight_layout();fig.savefig(root/'paired.pdf');fig.savefig(root/'paired.svg');plt.close(fig)
    print(json.dumps(groups,indent=2))


if __name__=='__main__':main()
