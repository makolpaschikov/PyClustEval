"""Real-UCI-only Gaussian aggregate DP protocol; NEVER substitutes synthetic data.

Usage:
  python tools/benchmark_dry_bean_gaussian_aggregate.py --arff /path/Dry_Bean_Dataset.arff
  python tools/benchmark_dry_bean_gaussian_aggregate.py --dataset digits

For Dry Bean validates real shape/class counts, runs matched clipped control and
DP epsilons; exports strict JSON + histories. Flower optional if installed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sklearn.datasets import load_digits
from clustering_eval.application import ComparisonService, RunRequest
from clustering_eval.results.history_store import HistoryStore
from clustering_eval.datasets.dry_bean import load_dry_bean


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--arff', type=Path, help='Official UCI Dry_Bean_Dataset.arff')
    parser.add_argument('--dataset', choices=['dry_bean','digits'], default='dry_bean')
    parser.add_argument('--backend', choices=['numpy','flower','adapted','all'], default='adapted', help='adapted=5 modified author-server DP variants, all=8 NumPy+adapted')
    parser.add_argument('--clip', type=float, default=4.0)
    parser.add_argument('--seeds', type=int, nargs='+', default=[42,43,44])
    parser.add_argument('--epsilons', type=float, nargs='+', default=[20,10,5,1])
    parser.add_argument('--out', type=Path, default=Path('dry_bean_gaussian_aggregate_results'))
    args = parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    if args.dataset == 'dry_bean':
        if args.arff:
            if not args.arff.is_file():
                parser.error(f'ARFF not found: {args.arff}')
            cache = args.out / 'dataset_cache' / 'dry_bean'
            cache.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(args.arff, cache / 'Dry_Bean_Dataset.arff')
            os.environ['PYCLUSTEVAL_DATA_DIR'] = str(cache.parent.resolve())
        try:
            data = load_dry_bean()
        except Exception as e:
            parser.error('Real UCI Dry Bean file REQUIRED; --arff PATH or cached '
                         f'download. No synthetic substitute. Error: {e}')
        if data.X.shape != (13611,16) or len(set(data.y.tolist())) != 7:
            parser.error('Dry Bean validation failed: expected 13,611 x 16, 7 classes')
        f = Path(data.metadata['data_path'])
        sha256 = hashlib.sha256(f.read_bytes()).hexdigest()
        print('VERIFIED REAL DRY BEAN:', data.X.shape, 'classes=7; sha256:',sha256)
    else:
        x=load_digits();sha256=hashlib.sha256(x.data.tobytes()).hexdigest()
        print('REAL SCIKIT-LEARN DIGITS:',x.data.shape)
    adapted = ('Adapted FKM','Adapted FKDC','Adapted HF_DBSCAN','Adapted NN-FC','Adapted p-FClus')
    numpy = ('fed_kmeans_numpy','fed_fuzzy_cmeans_numpy','fed_gmm_diag_numpy')
    flower = ('fed_kmeans_flower','fed_fuzzy_cmeans_flower','fed_gmm_diag_flower')
    algorithms = ({'numpy': numpy, 'flower': flower, 'adapted': adapted, 'all': adapted+numpy})[args.backend]
    service = ComparisonService(history_store=HistoryStore(args.out/'history'))
    rows=[]
    for seed in args.seeds:
        for eps in [None,*args.epsilons]:
            mode = 'public_clipped_control' if eps is None else 'gaussian_dp_aggregate'
            req = RunRequest(mode='federated', dataset_name=args.dataset,
                             algorithms=algorithms, num_clients=10, rounds=20,
                             partition_mode='iid',participation_rate=1.,dropout_rate=0.,
                             cluster_count_mode='known_k', seed=seed, privacy_mode=mode,
                             dp_clip_norm=args.clip, dp_epsilon=eps or 20., dp_delta=1e-5)
            report=service.compare(req)
            for rr in report.results:
                b=rr.model_state.get('benchmark') or {}
                row={'dataset':args.dataset,'source_sha256':sha256,'seed':seed,
                     'epsilon':eps,'mode':mode,'algorithm':rr.algorithm,
                     'ari':rr.ari,'ami':rr.ami,'nmi':rr.nmi,
                     'rounds':rr.rounds,
                     'dp_variant':rr.model_state.get('dp_variant'),
                     'author_algorithm_modified':bool(rr.model_state.get('not_equivalent_to_author_original',False)),
                     'assigned_fraction':(rr.model_state.get('diagnostics') or {}).get('assigned_fraction'),
                     'degenerate':(rr.model_state.get('diagnostics') or {}).get('degenerate'),
                     'clipped_fraction':report.privacy_report['public_preprocessing']['clipped_record_fraction_trusted_only'],
                     'estimated_sigma_per_round':rr.model_state.get('benchmark',{}).get('effective_params',{}).get('dp_aggregate',{}).get('sigma_per_coordinate'),
                     'experiment_id':report.experiment_id}
                rows.append(row)
                print(f"{args.dataset:8s} seed={seed} ε={str(eps):>4s} {rr.algorithm:<27s} ARI={str(rr.ari):>10s}",flush=True)
    out=args.out/'real_data_results.json'
    out.write_text(json.dumps(rows,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    print('SAVED',out)


if __name__ == '__main__':
    main()
