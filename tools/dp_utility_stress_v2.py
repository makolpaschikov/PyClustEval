"""Trusted diagnostic of noisy-input utility on real data; not a DP report.

Do NOT publish these metrics as DP: ARI uses original labels; benchmark
preprocessing and partitions see clean feature matrix and label distributions.
"""
from __future__ import annotations
import json
from pathlib import Path
from clustering_eval.application import ComparisonService,RunRequest
from clustering_eval.results.history_store import HistoryStore
from clustering_eval.results.public_release import build_public_report

out=Path('/mnt/data/timeeval_v2/dp_stress');out.mkdir(parents=True,exist_ok=True)
service=ComparisonService(history_store=HistoryStore(out/'history'))
rows=[]
for dataset in ('iris','wine'):
 for seed in (0,1,2):
  for eps in (None, 1.0, 5.0, 20.0):
   r=service.compare(RunRequest(mode='federated',dataset_name=dataset,
        algorithms=('fed_kmeans_numpy','fed_fuzzy_cmeans_numpy'),seed=seed,
        privacy_mode='none' if eps is None else 'gaussian_dp',
        dp_epsilon=5.0 if eps is None else eps,dp_delta=1e-5,dp_clip_norm=1.0,
        rounds=8))
   if eps is not None:
    assert not r.privacy_report['end_to_end_report_is_dp']
    try: build_public_report(r)
    except PermissionError: pass
    else: raise AssertionError('DP benchmark publicly releasable, privacy leak')
   for alg in r.results:
    rows.append({'dataset':dataset,'seed':seed,'epsilon':eps,'algorithm':alg.algorithm,
                 'ari_trusted_only':alg.ari,'ami_trusted_only':alg.ami,
                 'full_report_not_dp':eps is not None})
   (out/'trusted_utility_rows.json').write_text(json.dumps(rows,indent=2,allow_nan=False))
   print('CHECK',dataset,seed,eps,[(x.algorithm,round(x.ari,3)) for x in r.results],flush=True)
print('DONE',len(rows))
