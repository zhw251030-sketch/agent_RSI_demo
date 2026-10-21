"""Report every fixed slot from saved records; no fitting or model calls."""
import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from extensions.basis_trial_v02.verify import verify_run


def read(path):return json.loads(path.read_bytes())


def summarize(root=ROOT):
    output=root/'runs/basis-trial-v02/measured-v01'
    audit=verify_run(output,root/'docs/experiments/basis-trial-v02-preparation')
    summary=read(output/'experiment/summary.json');terminal=read(output/'result.json')
    budget=terminal['budget'];ledger=read(output/'budget-ledger.json')
    rows=[]
    for item in summary['rows'][1:]:
        slot=item['slot'];result=item['result'];fit=result['optimizer_diagnostics']
        rows.append(dict(id=slot['id'],parent=slot['parent'],arm=slot['arm'],
            feature_ids=item['submission']['feature_ids'],nmse=item['nmse'],parent_nmse=item['parent_nmse'],
            delta_nmse=item['delta_nmse'],outcome=item['outcome'],transition=item['transition'],
            structural_sha256=item['structural_sha256'],n_params=result['n_params'],optimizer_diagnostics=fit))
    groups=[]
    for parent in ('A','B'):
        for arm in ('S0','S1'):
            items=[r for r in rows if r['parent']==parent and r['arm']==arm]
            groups.append(dict(parent=parent,arm=arm,count=len(items),unique_structures=len({r['structural_sha256'] for r in items}),
                outcomes=dict(Counter(r['outcome'] for r in items)),nmse_values=[r['nmse'] for r in items],
                mean_nmse=sum(r['nmse'] for r in items)/len(items) if items else None,
                feature_id_lists=[r['feature_ids'] for r in items]))
    usages=[r.get('usage') for r in ledger['requests'] if r.get('usage')]
    known_tokens=sum(u['total_tokens'] for u in usages)
    report=dict(status=summary['status'],audit=audit,policy=summary['policy'],policy_no_change=summary['policy_no_change'],
        baselines={k:dict(nmse=v['metrics']['nmse'],params=v['params'],n_params=v['n_params']) for k,v in summary['baselines'].items()},
        rows=rows,groups=groups,budget=budget,known_tokens=known_tokens,
        cumulative=dict(research_requests=171+budget['request_count'],known_tokens=1390323+known_tokens,
            known_estimated_cost_cny=str(Decimal('4.2777252')+Decimal(str(budget['known_estimated_cost_cny']))),
            conservative_reserved_cny=str(Decimal('19.8218748')+Decimal(str(budget['reserved_cost_cny']))),
            prior_unknown_usage_count=2,actual_total_invoice_cny=None),
        activity=dict(new_model_requests=budget['request_count'],new_policy_proposals=int(summary['policy'] is not None),
            promoted_policies=0,new_weight_updates=0,sealed_access=0,analysis_model_requests=0,analysis_fits=0))
    fits=[read(p) for p in sorted((output/'experiment').glob('*/fit.json'))]
    report['activity']['fit_formula_calls']=sum(f['result']['diagnostics']['candidate_calls'] for f in fits)
    report['activity']['optimizer_formula_calls']=sum(f['result']['diagnostics']['optimizer_candidate_calls'] for f in fits)
    report['response_text']=[dict(slot=r['session_id'],characters=len((read(output/'sessions'/r['session_id']/'requests'/(r['request_id']+'.response.json'))['choices'][0]['message'].get('content') or ''))) for r in ledger['requests']]
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    target=ROOT/a.output
    if target.exists():raise FileExistsError('Analysis output exists')
    target.parent.mkdir(parents=True,exist_ok=True)
    report=summarize();target.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(report,ensure_ascii=False,allow_nan=False))
