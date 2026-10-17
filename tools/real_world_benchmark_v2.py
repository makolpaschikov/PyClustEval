"""Run real SKLEARN datasets end-to-end, not mocked unit fixtures.

This suite does not download or substitute nominal MNIST/Dry Bean. Real
MNIST/Dry Bean are only eligible if their official data are present.
"""
from __future__ import annotations
import argparse
import json
import os
import platform
from pathlib import Path
import sys
import traceback

import numpy as np
from sklearn.metrics import adjusted_rand_score
from clustering_eval.application import ComparisonService, RunRequest
from clustering_eval.datasets.registry import default_registry
from clustering_eval.metrics.paired_statistics import summarize_metric, paired_bootstrap
from clustering_eval.results.history_store import HistoryStore


LOCAL = ('kmeans', 'gmm', 'agglomerative', 'dbscan')
FED = ('fed_kmeans_numpy', 'fed_fuzzy_cmeans_numpy', 'fed_gmm_diag_numpy')


def json_safe(value):
    """Map undefined/invalid floats to JSON null; do not suppress failed runs."""
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def run(args):
    root = Path(args.out).resolve(); root.mkdir(parents=True, exist_ok=True)
    service = ComparisonService(history_store=HistoryStore(root / 'history'))
    registry = default_registry()
    rows=[]; errors=[]
    for dataset_name in args.datasets:
        try:
            d=registry.load(dataset_name)
            X=np.asarray(d.X); y=np.asarray(d.y)
            assert X.ndim==2 and X.shape[1] > 1 and len(np.unique(y)) >=2
            assert np.isfinite(X).all() and len(y) == len(X)
            metadata={"dataset":dataset_name, "shape":X.shape, "classes":len(np.unique(y)),
                      "source":d.metadata.get('source'), "baseline_shuffled_ari": float(adjusted_rand_score(y, np.random.default_rng(492).permutation(y)))}
            (root/f'{dataset_name}_source.json').write_text(json.dumps(metadata,indent=2,ensure_ascii=False))
            print('SOURCE',metadata, flush=True)
        except Exception as e:
            print('DATASET_UNAVAILABLE',dataset_name,repr(e),flush=True)
            errors.append({'dataset':dataset_name,'reason':repr(e)})
            continue
        for seed in range(args.seeds):
            conditions=[('local_known', dict(mode='local',algorithms=LOCAL,
                cluster_count_mode='known_k', tuning_mode='unsupervised'))]
            if args.include_estimated and seed < args.estimated_seeds:
                conditions.append(('local_estimated', dict(mode='local',algorithms=('kmeans','gmm'),
                    cluster_count_mode='estimated_k', estimated_k_max=12)))
            for pname, alpha, participation, drop in [
                ('iid_full',None,1.,0.),('dirichlet_01_full',.1,1.,0.),
                ('dirichlet_01_partial',.1,.5,.2),('iid_partial',None,.5,.2)]:
                if seed >= args.fed_seeds:
                    break
                conditions.append((pname,dict(mode='federated',algorithms=FED,num_clients=5,
                    partition_mode='iid' if alpha is None else 'dirichlet',
                    dirichlet_alpha=.5 if alpha is None else alpha,
                    participation_rate=participation,dropout_rate=drop,rounds=8)))
            for scenario, settings in conditions:
                if dataset_name == 'digits' and scenario == 'local_known' and args.no_digits_dbscan:
                    settings['algorithms'] = ('kmeans','gmm','agglomerative')
                print('RUN',dataset_name,seed,scenario,flush=True)
                try:
                    report=service.compare(RunRequest(dataset_name=dataset_name,seed=seed,**settings))
                    for r in report.results:
                        diagn=r.model_state['diagnostics']; bench=r.model_state['benchmark']
                        row={'dataset':dataset_name,'seed':seed,'scenario':scenario,'algorithm':r.algorithm,
                             'ari':r.ari,'ami':r.ami,'nmi':r.nmi,'silhouette':r.silhouette,
                             'coverage':diagn['assigned_fraction'],
                             'n_clusters':diagn['cluster_count_excluding_noise'],
                             'k':bench['target_clusters'], 'cluster_count_source':bench['cluster_count_source'],
                             'runtime_call':diagn['runtime_algorithm_call_sec'],
                             'runtime_wall_with_preprocessing':diagn['runtime_wall_including_preprocessing_sec'],
                             'communication_bytes_logical':r.communication_bytes,
                             'degenerate':diagn['degenerate'],'near_degenerate':diagn['near_degenerate'],
                             'client_worst_ari':(diagn['client_metrics'].get('ari') or {}).get('worst'),
                             'partition_fingerprint':report.partition.fingerprint if report.partition else None,
                             'partition_js':(report.partition.heterogeneity.get('class_js_divergence_weighted_bits') if report.partition else None),
                             'pred_hash':diagn['prediction_hash'],
                             'metric_schema':diagn['metric_schema_version'],
                             'tuning':diagn.get('unsupervised_parameter_tuning'),
                             'report_path':str(report.history_directory)}
                        assert -1.0 <= row['ari'] <= 1.0
                        assert -1.0 <= row['ami'] <= 1.0
                        assert 0 <= row['nmi'] <= 1.0
                        assert 0 <= row['coverage'] <= 1.0
                        assert row['runtime_call'] > 0
                        rows.append(row)
                        print('RES',r.algorithm, 'ari',round(r.ari,4),'ami',round(r.ami,4),
                              'coverage',round(row['coverage'],3),'clusters',row['n_clusters'],
                              'time',round(row['runtime_wall_with_preprocessing'],3),flush=True)
                    (root/'rows.json').write_text(json.dumps(json_safe(rows),ensure_ascii=False,indent=2,allow_nan=False,default=str))
                except Exception as e:
                    errors.append({'dataset':dataset_name,'seed':seed,'scenario':scenario,
                                   'error':repr(e),'stack':traceback.format_exc()})
                    print('ERROR',repr(e),flush=True)
                    (root/'errors.json').write_text(json.dumps(errors,ensure_ascii=False,indent=2))
    summaries={'rows':len(rows),'errors':errors,
               'ari':summarize_metric(rows,'ari'),
               'ami':summarize_metric(rows,'ami'),
               'federated_paired_ari_kmeans_minus_fuzzy':paired_bootstrap(rows,left='fed_kmeans_numpy',right='fed_fuzzy_cmeans_numpy'),
               'federated_paired_ari_kmeans_minus_gmm':paired_bootstrap(rows,left='fed_kmeans_numpy',right='fed_gmm_diag_numpy'),
               'environment':{'python':sys.version,'machine':platform.machine(),
                              'cpu_count':os.cpu_count(), 'cpu_threads_blas':os.environ.get('OPENBLAS_NUM_THREADS')}}
    (root/'summary.json').write_text(json.dumps(json_safe(summaries),ensure_ascii=False,indent=2,allow_nan=False,default=str))
    print('DONE',len(rows),'ROWS',len(errors),'ERRORS',flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',default='/mnt/data/TimeEval_Real_Data_Validation_2026-10-14')
    parser.add_argument('--datasets',nargs='+',default=['iris','wine','digits'])
    parser.add_argument('--seeds',type=int,default=5)
    parser.add_argument('--fed-seeds',type=int,default=5)
    parser.add_argument('--estimated-seeds',type=int,default=2)
    parser.add_argument('--include-estimated',action='store_true')
    parser.add_argument('--no-digits-dbscan',action='store_true')
    run(parser.parse_args())
