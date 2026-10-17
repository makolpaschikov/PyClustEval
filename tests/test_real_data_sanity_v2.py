"""Explicit real sklearn dataset smoke checks, not synthetic toy fixtures."""
from __future__ import annotations
import numpy as np
from sklearn.metrics import adjusted_rand_score
from clustering_eval.datasets.registry import default_registry
from clustering_eval.metrics.protocol_v2 import measure_partition_heterogeneity
from clustering_eval.datasets.partitioning import make_partition
from clustering_eval.algorithms.sklearn_algorithms import SklearnKMeans
from sklearn.preprocessing import StandardScaler


def test_real_sources_shape_class_balance_and_random_baseline():
    for name, shape, classes in [('iris',(150,4),3),('wine',(178,13),3),('digits',(1797,64),10)]:
        d=default_registry().load(name)
        assert d.X.shape == shape
        assert len(d.y) == len(d.X)
        assert len(np.unique(d.y)) == classes
        assert np.isfinite(d.X).all()
        shuffled=adjusted_rand_score(d.y,np.random.default_rng(2026).permutation(d.y))
        assert abs(shuffled) < .1


def test_real_kmeans_quality_is_plausible_not_perfect():
    for name, minimum, maximum in [('iris',.45,.98),('wine',.60,.99),('digits',.25,.90)]:
        data=default_registry().load(name)
        x=StandardScaler().fit_transform(data.X)
        model=SklearnKMeans().run(x,None,{'k':len(np.unique(data.y)), 'n_init':10},42)
        ari=adjusted_rand_score(data.y,model.labels)
        assert minimum < ari < maximum, (name,ari)


def test_real_digits_label_skew_is_actually_stronger_than_iid():
    data=default_registry().load('digits')
    for seed in (0,1,2):
        def score(mode):
            p=make_partition(mode,len(data.X),5,seed,y=data.y,alpha=.1,min_samples_per_client=3)
            return measure_partition_heterogeneity(p,data.y)['class_js_divergence_weighted_bits']
        assert score('dirichlet') > score('iid')
