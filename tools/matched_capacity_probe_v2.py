"""A capacity-matched *probe*, NOT an exact computational-cost equivalence."""
from __future__ import annotations
import json
from pathlib import Path
from clustering_eval.application import ComparisonService, RunRequest
from clustering_eval.results.history_store import HistoryStore


def main():
    root=Path('/mnt/data/timeeval_v2/matched_probe');root.mkdir(exist_ok=True,parents=True)
    service=ComparisonService(history_store=HistoryStore(root/'history'))
    rows=[]
    for dataset in ('iris','wine','digits'):
        for seed in (0,1):
            local=service.compare(RunRequest(dataset_name=dataset,seed=seed,mode='local',
                   algorithms=('kmeans','gmm'),max_iter=8,
                   algorithm_params_by_name={'kmeans':{'n_init':1},'gmm':{'covariance_type':'diag','n_init':1}}))
            fed=service.compare(RunRequest(dataset_name=dataset,seed=seed,mode='federated',
                   algorithms=('fed_kmeans_numpy','fed_gmm_diag_numpy'), rounds=8, num_clients=5))
            for r in local.results+fed.results:
                rows.append({'dataset':dataset,'seed':seed,'algorithm':r.algorithm,
                             'ari':r.ari,'ami':r.ami,
                             'wall_call_sec':r.model_state['diagnostics']['runtime_wall_including_preprocessing_sec'],
                             'logical_bytes':r.communication_bytes,
                             'note':'Rough model capacity / iteration budget controls only; NOT equal time, initialization, or communication.'})
    (root/'matched_probe.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2,allow_nan=False))
    print(len(rows),'probe records')
    for r in rows:print(r['dataset'],r['seed'],r['algorithm'],round(r['ari'],4),flush=True)
if __name__=='__main__':main()
