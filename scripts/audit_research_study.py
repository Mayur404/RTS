"""Audit every study trace, bind source archives, and reproduce paired intervals."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.audit_research_trace import audit_manifest
from scripts.run_research_suite import bootstrap
from rts_predictive.dashboard.research_projection import paired_comparison


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


AUDITOR_SHA256=digest(__file__)


def main():
    p=argparse.ArgumentParser();p.add_argument('aggregate');p.add_argument('--output',required=True)
    p.add_argument('--trace-cache',help='Reuse a passing trace audit only when raw files and auditor identities match')
    args=p.parse_args();path=Path(args.aggregate);study=json.loads(path.read_bytes())
    audits=[];sources=set();models=set();archive_hashes=set()
    for i,row in enumerate(study['pairs'],1):
        configurations=set();metrics={}
        for policy,ref in row['manifest_files'].items():
            manifest_path=Path(ref['path']);assert digest(manifest_path)==ref['sha256']
            m=json.loads(manifest_path.read_bytes());assert m['status']=='COMPLETE'
            assert m['seed']==row['seed'] and m['family']==row['family']
            assert m['pair_id']==row['pair_id'] and m['policy']==policy
            archive=manifest_path.parent.parent/'source.zip'
            assert digest(archive)==m['source_archive_sha256']
            archive_hashes.add(m['source_archive_sha256'])
            with zipfile.ZipFile(archive) as z:
                h=hashlib.sha256()
                for name in sorted(n for n in z.namelist() if n.startswith('rts_predictive/') and n.endswith('.py')):
                    b=name.encode();h.update(len(b).to_bytes(4,'big'));h.update(b)
                    h.update(hashlib.sha256(z.read(name)).digest())
                assert h.hexdigest()==m['source_sha256']
                if m.get('models'):
                    assert hashlib.sha256(z.read('models/research_gnn.pt')).hexdigest()==m['models']['gnn_sha256']
                    assert hashlib.sha256(z.read('models/federated_remote_estimator.pt')).hexdigest()==m['models']['remote_sha256']
                    models.add(m['models']['gnn_sha256'])
            sources.add(m['source_sha256']);configurations.add(m['configuration_hash'])
            if args.trace_cache:
                from scripts.audit_study_incremental import cached_audit
                audit=cached_audit(manifest_path,args.trace_cache)
            else:audit=audit_manifest(manifest_path)
            assert audit['status']=='PASS'
            audits.append(audit)
            metrics[policy]=json.loads((manifest_path.parent/'metrics.json').read_bytes())
        assert len(configurations)==1
        assert metrics[study['baseline']]==row['before'] and metrics['protected']==row['after']
        comparison=paired_comparison(metrics[study['baseline']],metrics['protected'])
        assert all(row[k]==v for k,v in comparison.items())
        print(f'PASS paired trace {i}/{len(study["pairs"])}: {row["family"]} seed {row["seed"]}',flush=True)
    for family,g in study['groups'].items():
        rows=[r for r in study['pairs'] if r['family']==family]
        effects=[r['change_pp'] for r in rows]
        assert g['paired_seeds']==len(rows)
        assert g['mean_before_pct']==sum(r['before_pct'] for r in rows)/len(rows)
        assert g['mean_after_pct']==sum(r['after_pct'] for r in rows)/len(rows)
        assert g['mean_change_pp']==sum(effects)/len(rows)
        assert g['paired_bootstrap_95_ci_pp']==bootstrap(effects)
        assert g['bootstrap_replicates']==5000 and g['bootstrap_seed']==91
        assert g['regressed_seeds']==sum(e<0 for e in effects)
    report={'status':'PASS','evidence':'SIMULATED','aggregate_file':str(path.resolve()),
            'aggregate_sha256':digest(path),'paired_runs':len(study['pairs']),
            'policy_traces':len(audits),'canonical_events':sum(a['canonical_events'] for a in audits),
            'python_source_sha256':sorted(sources),'gnn_sha256':sorted(models),
            'source_archive_versions':len(archive_hashes),'bootstrap_reproduced':True,
            'auditor_sha256':AUDITOR_SHA256,'trace_cache':args.trace_cache,'audits':audits}
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='audits'}))


if __name__=='__main__':main()
