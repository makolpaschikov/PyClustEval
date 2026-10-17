from __future__ import annotations
import numpy as np
import pytest
from sklearn.datasets import load_iris, load_digits

from clustering_eval.application import RunRequest, ComparisonService
from clustering_eval.privacy.aggregate_dp import (
    public_scaled_features, clipped_public_features, make_dp_aggregate_config,
    noisy_joint_aggregate, public_initial_centers, project_centers,
)
from clustering_eval.results.history_store import HistoryStore
from clustering_eval.results.public_release import build_public_report


def test_public_dry_bean_reference_is_fixed_and_clipping_is_bounded():
    fake_two_records = np.array([[69718.99, 969.54, 362.43, 227.47, 1.597, 0.7558,
                                  70681.22,285.52,0.7525,0.9868,0.8637,0.796,
                                  0.006,0.002,0.638,0.994], [0]*16])
    X, r = clipped_public_features(fake_two_records, 'dry_bean', 4.0)
    assert np.linalg.norm(X, axis=1).max() <= 4 + 1e-9
    assert r['private_data_fitted_scaler'] is False
    x0, _ = public_scaled_features(fake_two_records, 'dry_bean')
    x1, _ = public_scaled_features(fake_two_records[:1], 'dry_bean')
    np.testing.assert_array_equal(x0[0], x1[0])


def test_composed_noise_sensitivity_budget_and_crypto_randomness():
    k = make_dp_aggregate_config(kind='kmeans', epsilon=20, delta=1e-5,
                                 clip_norm=4., rounds=20, enabled=True)
    g = make_dp_aggregate_config(kind='gmm', epsilon=20, delta=1e-5,
                                 clip_norm=4., rounds=20, enabled=True)
    assert k['epsilon_per_round'] == pytest.approx(1.)
    assert k['delta_per_round'] == pytest.approx(5e-7)
    assert g['sensitivity_per_round'] > k['sensitivity_per_round']
    assert g['sigma_per_coordinate'] > k['sigma_per_coordinate'] > 0
    a = noisy_joint_aggregate(k, np.zeros((10, 4)))[0]
    b = noisy_joint_aggregate(k, np.zeros((10, 4)))[0]
    assert not np.array_equal(a, b)
    no_noise = make_dp_aggregate_config(kind='kmeans', epsilon=20, delta=1e-5,
                                       clip_norm=4, rounds=20, enabled=False)
    assert np.array_equal(noisy_joint_aggregate(no_noise, a)[0], a)
    assert np.isfinite(project_centers(np.array([[np.inf, 2.]]), 4)).all()


def test_service_aggregate_dp_end_to_end_real_iris(tmp_path):
    service = ComparisonService(history_store=HistoryStore(tmp_path/'history'))
    opts = dict(mode='federated', dataset_name='iris', num_clients=10,
                algorithms=('fed_kmeans_numpy','fed_fuzzy_cmeans_numpy','fed_gmm_diag_numpy'),
                rounds=20, dp_epsilon=20, dp_delta=1e-5, dp_clip_norm=4.)
    control = service.compare(RunRequest(**opts, privacy_mode='public_clipped_control'))
    private = service.compare(RunRequest(**opts, privacy_mode='gaussian_dp_aggregate'))
    assert private.privacy_report['upper_bound_epsilon_across_selected_algorithms'] == 60
    assert private.privacy_report['public_preprocessing']['private_data_fitted_scaler'] is False
    assert private.privacy_report['end_to_end_report_is_dp'] is False
    assert len(private.results) == len(control.results) == 3
    assert all(np.isfinite(z.ari) for z in private.results)
    for z in private.results:
        assert z.model_state['benchmark']['privacy_mode'] == 'gaussian_dp_aggregate'
    with pytest.raises(PermissionError):
        build_public_report(private)


def test_misconfiguration_is_rejected_before_run(tmp_path):
    service = ComparisonService(history_store=HistoryStore(tmp_path/'history'))
    with pytest.raises(ValueError, match='clip norm to 4'):
        RunRequest(mode='federated',dataset_name='dry_bean',
            algorithms=('fed_kmeans_numpy', 'fed_gmm_diag_numpy'),
            privacy_mode='gaussian_dp_aggregate',dp_clip_norm=100000).validate()
    # Five author-server DP proxy variants are now enabled, with explicit fidelity warning.
    report = service.compare(RunRequest(mode='federated',dataset_name='iris',
             algorithms=('Adapted NN-FC','fed_kmeans_numpy'),
             privacy_mode='gaussian_dp_aggregate',dp_clip_norm=4))
    assert report.results[0].algorithm.endswith('[DP proxy]')
    assert report.results[0].model_state['not_equivalent_to_author_original'] is True


def test_public_reference_other_real_datasets():
    for name, loader in [('iris',load_iris),('digits',load_digits)]:
        X = loader().data
        arr, ref = clipped_public_features(X, name, 4)
        assert arr.shape == X.shape
        assert np.isfinite(arr).all()
        assert np.max(np.linalg.norm(arr, axis=1)) < 4.00000001
        assert not ref['private_data_fitted_scaler']
