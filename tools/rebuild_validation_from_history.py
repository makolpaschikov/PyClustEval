"""Rebuild an empirical audit even when an external suite writer failed.

Only uses persisted successful `ComparisonReport`s; never fabricates entries.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import numpy as np
from clustering_eval.metrics.paired_statistics import paired_bootstrap, summarize_metric
from real_world_benchmark_v2 import json_safe


def derive_scenario(req):
    if req['mode']=='local':
        return 'local_estimated' if req['cluster_count_mode']=='estimated_k' else 'local_known'
    base=('dirichlet_01' if req['partition_mode']=='dirichlet' else 'iid')
    if req['participation_rate'] < 1 or req['dropout_rate'] > 0:
        return base+'_partial'
    return base+'_full'


def main(source_root, dest):
    paths=sorted(Path(source_root).glob('validated_*/history/*/report.json'))
    if not paths:
        raise SystemExit('No saved comparison reports found')
    rows=[]; ids=set(); n_comparisons=0
    for path in paths:
        report=json.loads(path.read_text())
        if report['experiment_id'] in ids:
            raise AssertionError('Repeated experiment ID')
        ids.add(report['experiment_id']); n_comparisons+=1
        req=report['request']; scenario=derive_scenario(req)
        for result in report['results']:
            state=result['model_state']; diag=state['diagnostics']; bench=state['benchmark']
            rows.append({'dataset':req['dataset_name'], 'seed':req['seed'], 'scenario':scenario,
                         'algorithm':result['algorithm'], 'ari':result['ari'], 'ami':result.get('ami'),
                         'nmi':result['nmi'], 'silhouette':result['silhouette'],
                         'coverage':diag['assigned_fraction'],
                         'n_clusters':diag['cluster_count_excluding_noise'],
                         'k':bench['target_clusters'], 'cluster_count_source':bench['cluster_count_source'],
                         'runtime_wall_with_preprocessing':diag['runtime_wall_including_preprocessing_sec'],
                         'logical_communication_bytes':result['communication_bytes'],
                         'degenerate':diag['degenerate'], 'near_degenerate':diag['near_degenerate'],
                         'client_worst_ari':(diag['client_metrics'].get('ari') or {}).get('worst'),
                         'partition_fingerprint':report['partition']['fingerprint'] if report['partition'] else None,
                         'partition_js':(report['partition']['heterogeneity'].get('class_js_divergence_weighted_bits') if report['partition'] else None),
                         'pred_hash':diag['prediction_hash'], 'metric_schema':diag['metric_schema_version'],
                         'tuning':diag.get('unsupervised_parameter_tuning'), 'history':str(path.parent)})
    summaries={'n_comparisons':n_comparisons,'n_results':len(rows),
               'unique_conditions':sorted(set((r['dataset'],r['scenario']) for r in rows)),
               'ari':summarize_metric(rows,'ari'),
               'ami':summarize_metric(rows,'ami'),
               'kmeans_minus_fuzzy_paired':paired_bootstrap(rows,left='fed_kmeans_numpy',right='fed_fuzzy_cmeans_numpy'),
               'kmeans_minus_diag_gmm_paired':paired_bootstrap(rows,left='fed_kmeans_numpy',right='fed_gmm_diag_numpy'),
               'degenerate_counts':{}, 'invariance_cases':[]}
    for dataset in sorted(set(r['dataset'] for r in rows)):
        for algorithm in sorted(set(r['algorithm'] for r in rows)):
            cases=[r for r in rows if r['dataset']==dataset and r['algorithm']==algorithm]
            if cases:
                summaries['degenerate_counts'][dataset+' / '+algorithm]=sum(bool(r['degenerate']) for r in cases)
        for seed in sorted(set(r['seed'] for r in rows)):
            for algorithm in ('fed_kmeans_numpy','fed_fuzzy_cmeans_numpy','fed_gmm_diag_numpy'):
                a=[r for r in rows if r['dataset']==dataset and r['seed']==seed and r['algorithm']==algorithm and r['scenario']=='iid_full']
                b=[r for r in rows if r['dataset']==dataset and r['seed']==seed and r['algorithm']==algorithm and r['scenario']=='dirichlet_01_full']
                if a and b:
                    summaries['invariance_cases'].append({'dataset':dataset,'seed':seed,'algorithm':algorithm,
                              'same_ari':np.isclose(a[0]['ari'],b[0]['ari']),
                              'same_prediction':a[0]['pred_hash']==b[0]['pred_hash'],
                              'iid_js':a[0]['partition_js'],'dirichlet_js':b[0]['partition_js']})
    dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
    (dest/'empirical_rows.json').write_text(json.dumps(json_safe(rows),ensure_ascii=False,indent=2,allow_nan=False))
    (dest/'empirical_summary.json').write_text(json.dumps(json_safe(summaries),ensure_ascii=False,indent=2,allow_nan=False))
    print('Reconstructed',n_comparisons,'actual comparisons,',len(rows),'actual algorithm results')
    print('Invariances:',sum(x['same_ari'] for x in summaries['invariance_cases']),'/',len(summaries['invariance_cases']))
    print('degenerates:',sum(summaries['degenerate_counts'].values()))
    for item in summaries['ari']:
        print(item)

if __name__=='__main__': main(sys.argv[1],sys.argv[2])
