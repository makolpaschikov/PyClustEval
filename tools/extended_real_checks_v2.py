"""Extended real-data stress: 10 paired seeds, matched controls, DP stress.

No synthetic inputs or mock algorithms. All results persist in JSON with
undefined scores represented as null. Never claim trusted reports are DP.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import numpy as np
from clustering_eval.application import ComparisonService, RunRequest
from clustering_eval.results.history_store import HistoryStore
from clustering_eval.metrics.paired_statistics import paired_bootstrap, summarize_metric
from real_world_benchmark_v2 import json_safe


def main(args):
    root=Path(args.out);root.mkdir(parents=True,exist_ok=True)
    service=ComparisonService(history_store=HistoryStore(root/'history'))
    rows=[]
    for dataset in args.datasets:
        for seed in range(args.start_seed, args.seeds):
            for p_mode, alpha, participation, dropout in [
                ('iid',.5,1.0,0.0),('dirichlet',.1,1.0,0.0),
                ('iid',.5,.5,.2),('dirichlet',.1,.5,.2)]:
                scenario=('iid' if p_mode=='iid' else 'label_skew_alpha_0.1')+('_full' if participation==1 else '_partial')
                req=RunRequest(dataset_name=dataset, mode='federated',
                               algorithms=('fed_kmeans_numpy','fed_fuzzy_cmeans_numpy','fed_gmm_diag_numpy'),
                               num_clients=5,partition_mode=p_mode,dirichlet_alpha=alpha,
                               participation_rate=participation,dropout_rate=dropout,
                               seed=seed,rounds=8)
                report=service.compare(req)
                for r in report.results:
                    diag=r.model_state['diagnostics']
                    rows.append({'dataset':dataset,'seed':seed,'scenario':scenario,'algorithm':r.algorithm,
                                 'ari':r.ari,'ami':r.ami,'silhouette':r.silhouette,
                                 'coverage':diag['assigned_fraction'],
                                 'pred_hash':diag['prediction_hash'],
                                 'partition_fingerprint':report.partition.fingerprint,
                                 'realized_js':report.partition.heterogeneity['class_js_divergence_weighted_bits'],
                                 'worst_client_ari':diag['client_metrics']['ari']['worst'],
                                 'logical_bytes':r.communication_bytes,
                                 'elapsed_wall_sec':diag['runtime_wall_including_preprocessing_sec'],
                                 'degenerate':diag['degenerate']})
                (root/'rows.json').write_text(json.dumps(json_safe(rows),ensure_ascii=False,indent=2,allow_nan=False))
                print('COMPLETED',dataset,seed,scenario, 'rows',len(rows),flush=True)
    result={'n':len(rows),'by_algorithm':summarize_metric(rows,'ari'),
            'fed_kmeans_minus_fuzzy':paired_bootstrap(rows,left='fed_kmeans_numpy',right='fed_fuzzy_cmeans_numpy'),
            'fed_kmeans_minus_diag_gmm':paired_bootstrap(rows,left='fed_kmeans_numpy',right='fed_gmm_diag_numpy')}
    (root/'summary.json').write_text(json.dumps(json_safe(result),ensure_ascii=False,indent=2,allow_nan=False))
    print('DONE',len(rows),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--seeds',type=int,default=10);p.add_argument('--start-seed',type=int,default=0);p.add_argument('--datasets',nargs='+',default=['digits'])
    main(p.parse_args())
