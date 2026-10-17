"""End-to-end regression tests of author-server DP surrogate variants."""
from __future__ import annotations
import numpy as np
import pytest
from clustering_eval.application import ComparisonService, RunRequest
from clustering_eval.results.history_store import HistoryStore
from clustering_eval.results.public_release import build_public_report

AUTHORS = ('Adapted FKM', 'Adapted FKDC', 'Adapted HF_DBSCAN',
           'Adapted NN-FC', 'Adapted p-FClus')

@pytest.mark.parametrize('privacy', ['public_clipped_control', 'gaussian_dp_aggregate'])
def test_all_five_authors_end_to_end_real_iris(privacy, tmp_path):
    srv = ComparisonService(history_store=HistoryStore(tmp_path))
    report = srv.compare(RunRequest(mode='federated', dataset_name='iris',
        algorithms=AUTHORS, num_clients=10, rounds=20, seed=42,
        privacy_mode=privacy, dp_epsilon=20., dp_delta=1e-5, dp_clip_norm=4.))
    assert len(report.results) == 5
    assert report.privacy_report['end_to_end_report_is_dp'] is False
    assert report.privacy_report['comparability_warning']
    if privacy == 'gaussian_dp_aggregate':
        assert report.privacy_report['upper_bound_epsilon_across_selected_algorithms'] == 100.
    for result in report.results:
        assert result.algorithm.endswith(' [DP proxy]')
        assert result.backend == 'author-server DP proxy'
        assert np.isfinite(result.ari)
        assert np.isfinite(result.ami)
        assert result.model_state['not_equivalent_to_author_original']
        expected_rounds = 20 if result.model_state['author_algorithm'] == 'Adapted FKM' else 1
        assert result.model_state['dp_budgeted_rounds'] == expected_rounds
        assert len(result.history) == expected_rounds
        assert result.model_state['benchmark']['privacy_mode'] == privacy
        assert result.communication_bytes >= 0
    with pytest.raises(PermissionError):
        build_public_report(report)


def test_repeated_dp_runs_are_independent_of_public_seed(tmp_path):
    srv = ComparisonService(history_store=HistoryStore(tmp_path))
    args = dict(mode='federated',dataset_name='iris',num_clients=10,rounds=4,
                seed=42, algorithms=('Adapted FKM','Adapted FKDC'),
                privacy_mode='gaussian_dp_aggregate',dp_epsilon=20,dp_delta=1e-5,dp_clip_norm=4)
    a = srv.compare(RunRequest(**args))
    b = srv.compare(RunRequest(**args))
    assert a.results[0].model_state['global_centers'] != b.results[0].model_state['global_centers']


def test_author_original_not_executed_in_aggregate_dp(monkeypatch, tmp_path):
    import clustering_eval.algorithms.author_adapters as au
    def deny(*a, **kw):
        raise AssertionError('Private author local routines must not execute in DP mode')
    monkeypatch.setattr(au, '_capture_author_labels', deny)
    srv = ComparisonService(history_store=HistoryStore(tmp_path))
    report = srv.compare(RunRequest(mode='federated',dataset_name='iris',
        algorithms=('Adapted FKDC','Adapted NN-FC'),privacy_mode='gaussian_dp_aggregate',
        dp_epsilon=20,dp_delta=1e-5,dp_clip_norm=4, rounds=3))
    assert len(report.results) == 2


def test_no_change_to_original_author_behavior(tmp_path):
    srv = ComparisonService(history_store=HistoryStore(tmp_path))
    report = srv.compare(RunRequest(mode='federated',dataset_name='iris',
        algorithms=('Adapted FKM','Adapted p-FClus'),privacy_mode='none',rounds=3))
    assert all('[DP proxy]' not in r.algorithm for r in report.results)
    assert all(not r.model_state.get('not_equivalent_to_author_original') for r in report.results)

@pytest.mark.parametrize('dataset', ['wine', 'digits'])
def test_aggregate_dp_all_eight_on_real_sklearn_dataset(dataset, tmp_path):
    """Integration check on actual, not mock/synthetic datasets."""
    algorithms = AUTHORS + ('fed_kmeans_numpy','fed_fuzzy_cmeans_numpy','fed_gmm_diag_numpy')
    srv = ComparisonService(history_store=HistoryStore(tmp_path))
    report = srv.compare(RunRequest(mode='federated', dataset_name=dataset,
         num_clients=10, seed=42, rounds=20, algorithms=algorithms,
         privacy_mode='gaussian_dp_aggregate', dp_epsilon=20,
         dp_delta=1e-5, dp_clip_norm=4))
    assert len(report.results) == 8
    assert all(np.isfinite(r.ari) and np.isfinite(r.ami) for r in report.results)
    assert all(0 <= r.model_state['diagnostics']['assigned_fraction'] <= 1 for r in report.results)
    assert sum(bool(r.model_state.get('not_equivalent_to_author_original')) for r in report.results) == 5
    assert report.privacy_report['upper_bound_epsilon_across_selected_algorithms'] == 160


def test_density_dp_two_stage_accounting(tmp_path):
    srv = ComparisonService(history_store=HistoryStore(tmp_path))
    report = srv.compare(RunRequest(mode='federated', dataset_name='iris',
        algorithms=('Adapted HF_DBSCAN','Adapted FKDC'),num_clients=10,
        privacy_mode='gaussian_dp_aggregate',dp_epsilon=20,dp_delta=1e-5,dp_clip_norm=4))
    state = report.results[0].model_state
    assert state['dp_sigma_prototype_per_coordinate'] > 0
    assert state['dp_sigma_histogram_per_coordinate'] > 0
    assert 'epsilon/2' in state['privacy_budget_split']
    assert state['dp_density_projection'] == 'public-seeded random orthonormal 2D projection'
    assert state['rounds'] == 1
