from __future__ import annotations
import numpy as np
import pytest
from sklearn.datasets import load_iris, make_blobs
from clustering_eval.metrics.protocol_v2 import (measure_partition_heterogeneity,
    estimate_k_unlabeled, tune_dbscan_unlabeled)
from clustering_eval.metrics.paired_statistics import paired_bootstrap
from clustering_eval.metrics.clustering import compute_metrics
from clustering_eval.application import ComparisonService, RunRequest
from clustering_eval.results.history_store import HistoryStore
from clustering_eval.results.public_release import build_public_report


def test_ami_is_permutation_invariant_and_class_adjusted():
    X, y = load_iris(return_X_y=True)
    assert compute_metrics(X, y, y, ['ami'])['ami'] == pytest.approx(1.)
    assert compute_metrics(X, y, (y+1)%3, ['ami'])['ami'] == pytest.approx(1.)


def test_heterogeneity_iid_vs_pure_partitions():
    y = np.repeat([0,1], 100)
    iid = [np.r_[np.arange(0, 50), np.arange(100, 150)],
           np.r_[np.arange(50,100), np.arange(150,200)]]
    pure = [np.arange(100), np.arange(100, 200)]
    h0 = measure_partition_heterogeneity(iid,y)
    h1 = measure_partition_heterogeneity(pure,y)
    assert h0['class_js_divergence_weighted_bits'] == pytest.approx(0.)
    assert h1['class_js_divergence_weighted_bits'] > 0.3
    assert h0['size_cv'] == h1['size_cv'] == 0.


def test_estimated_k_reproducible_without_y():
    X, y = make_blobs(n_samples=170, centers=3, random_state=17, cluster_std=.5)
    k1, d1 = estimate_k_unlabeled(X,seed=42,maximum=5,sample_size=100)
    k2, d2 = estimate_k_unlabeled(X,seed=42,maximum=5,sample_size=100)
    assert (k1,d1)==(k2,d2)
    assert k1 >= 2


def test_dbscan_tuning_label_free_reproducible():
    X, _ = make_blobs(n_samples=180, centers=3, random_state=17, cluster_std=.25)
    a, d1 = tune_dbscan_unlabeled(X,seed=17)
    b, d2 = tune_dbscan_unlabeled(X,seed=17)
    assert a == b and d1 == d2
    assert len(d1['candidates']) == 8


def test_paired_ci_requires_matching_pair_id():
    rows = [dict(dataset='d',scenario='iid',algorithm=a,seed=i, partition_fingerprint=f'p{i}',ari=v)
            for i in range(5) for a,v in [('A',.8),('B',.7)]]
    result = paired_bootstrap(rows,left='A',right='B')[0]
    assert result['n_pairs'] == 5
    assert result['mean_difference'] == pytest.approx(.1)
    assert result['bootstrap_ci_95'] == pytest.approx([.1,.1])


def test_real_iris_known_and_estimated_and_public_report(tmp_path):
    service = ComparisonService(history_store=HistoryStore(tmp_path/'history'))
    r = service.compare(RunRequest(mode='local',dataset_name='iris',algorithms=('kmeans','gmm'),
                                  cluster_count_mode='estimated_k', estimated_k_max=5))
    assert r.results[0].ami is not None
    assert r.results[0].model_state['benchmark']['cluster_count_source'] == 'estimated_unlabeled_silhouette'
    assert 'publication_note' in build_public_report(r)


def test_private_release_blocked(tmp_path):
    service = ComparisonService(history_store=HistoryStore(tmp_path/'history'))
    r = service.compare(RunRequest(mode='federated',dataset_name='iris',
                    algorithms=('fed_kmeans_numpy','fed_fuzzy_cmeans_numpy'),
                    privacy_mode='gaussian_dp'))
    with pytest.raises(PermissionError):
        build_public_report(r)


def test_undefined_metric_serializes_as_json_null(tmp_path):
    import json
    from clustering_eval.results.history_store import _strict_json_value
    cleaned=_strict_json_value({'score':float('nan'),'bad':float('inf'),'ok':0.0,
                               'nested':np.array([1.,float('-inf')])})
    assert cleaned == {'score':None,'bad':None,'ok':0.,'nested':[1.,None]}
    assert 'NaN' not in json.dumps(cleaned, allow_nan=False)


def test_paired_scenario_delta_uses_seed_pairing_not_independent_means():
    from clustering_eval.metrics.paired_statistics import paired_scenario_delta
    rows=[{'dataset':'d','seed':i,'scenario':scenario,'algorithm':'A','ari':before + delta}
          for i,before in enumerate([.5,.8,.7])
          for scenario,delta in [('full',0.0),('partial',-.2)]]
    result=paired_scenario_delta(rows,algorithm='A',before='full',after='partial')[0]
    assert result['n_paired_seeds']==3
    assert result['mean_after_minus_before']==pytest.approx(-.2)
    assert result['bootstrap_ci_95']==pytest.approx([-.2,-.2])
