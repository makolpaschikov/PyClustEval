"""Fixed datasets and pre-registered nine-seed experiment plans."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
os.environ.setdefault('PYCLUSTEVAL_DATA_DIR','/workspace/.cache/pyclusteval/datasets')
sys.path.insert(0,'/workspace/PyClustEval')
import numpy as np
from sklearn.preprocessing import StandardScaler, MinMaxScaler
from clustering_eval.datasets.registry import default_registry
from clustering_eval.datasets.partitioning import make_partition, partition_class_counts, partition_fingerprint
from clustering_eval.metrics.protocol_v2 import measure_partition_heterogeneity
from clustering_eval.privacy.aggregate_dp import clipped_public_features

ROOT=Path(__file__).resolve().parent
OUT=Path('/workspace/artifacts/benchmark_3x3_20261028')
SEEDS={'drybean':('dry_bean',[17,43,101]),'mnist':('mnist_10k',[211,307,401]),
       'synthetic':('synthetic_anisotropic',[503,601,709])}
ALGORITHMS=['Adapted FKDC','Adapted FKM','Adapted HF_DBSCAN','Adapted NN-FC','Adapted p-FClus',
            'fed_fuzzy_cmeans_flower','fed_gmm_diag_flower','fed_kmeans_flower']

def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def digest(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()

def synthetic():
    """Eight overlapping heteroscedastic Gaussian populations in 24D.

    Twelve informative dimensions and twelve independent nuisance dimensions;
    random component orientations, unequal sizes, and one global rotation.
    All distribution parameters are public and chosen before benchmarking.
    """
    seed=314159; rng=np.random.default_rng(seed)
    counts=np.array([2640,2160,1800,1560,1320,1080,840,600])
    k=8; signal=12; nuisance=12; d=signal+nuisance
    means0=np.concatenate([rng.normal(0,1.0,(k,signal)),np.zeros((k,nuisance))],axis=1)
    rotation,_=np.linalg.qr(rng.normal(size=(d,d)))
    covs0=[]; blocks=[]; labels=[]
    for c,n in enumerate(counts):
        q,_=np.linalg.qr(rng.normal(size=(signal,signal)))
        eigenvalues=np.geomspace(.15,3.,signal)*np.linspace(.7,1.4,k)[c]**2
        cov=np.zeros((d,d)); cov[:signal,:signal]=(q*eigenvalues)@q.T
        cov[signal:,signal:]=np.eye(nuisance)*1.25**2
        covs0.append(cov)
        blocks.append(rng.multivariate_normal(means0[c],cov,size=int(n)))
        labels.append(np.full(n,c,dtype=np.int64))
    X=np.concatenate(blocks)@rotation; y=np.concatenate(labels)
    order=rng.permutation(len(X)); X=X[order]; y=y[order]
    means=means0@rotation
    covs=np.asarray([rotation.T@c@rotation for c in covs0])
    weights=counts/counts.sum()
    public_center=weights@means
    public_var=weights@(np.diagonal(covs,axis1=1,axis2=2)+means**2)-public_center**2
    public_scale=np.sqrt(public_var)
    meta=dict(source='pre-registered synthetic heteroscedastic Gaussian mixture',
        generator_seed=seed,n_samples=len(X),n_features=d,n_classes=k,
        informative_dimensions=signal,nuisance_dimensions=nuisance,
        component_counts=counts.tolist(),global_rotation=True,
        informative_covariance_condition_number=20.,nuisance_std=1.25,
        generator='reproduce/prepare.py:synthetic',
        public_center=public_center.tolist(),public_scale=public_scale.tolist(),
        public_reference_note='Exact mixture moments from public generator parameters; not fitted on realized samples')
    return X,y,meta,dict(means=means,covariances=covs,weights=weights,rotation=rotation)

def prepare(kind):
    dataset,seeds=SEEDS[kind]
    cache=ROOT/'cache'/dataset; cache.mkdir(parents=True,exist_ok=True)
    data_out=OUT/'datasets'/dataset; data_out.mkdir(parents=True,exist_ok=True)
    if kind=='synthetic':
        X,y,metadata,parameters=synthetic()
        np.savez_compressed(data_out/'generator_parameters.npz',**parameters)
    else:
        data=default_registry().load(dataset)
        X=np.asarray(data.X,dtype=np.float64); y=np.asarray(data.y); metadata=dict(data.metadata)
    expected={'drybean':(13611,16),'mnist':(10000,784),'synthetic':(12000,24)}[kind]
    assert X.shape==expected and y.shape==(len(X),) and np.isfinite(X).all()
    assert len(np.unique(y))=={'drybean':7,'mnist':10,'synthetic':8}[kind]
    if kind=='drybean':
        assert np.bincount(y).tolist()==[1322,522,1630,3546,1928,2027,2636]
        manifest=ROOT/'drybean_source.json'
        if manifest.exists():metadata['actual_source']=json.loads(manifest.read_text())
    if kind=='mnist':
        previous=json.loads(Path('/workspace/artifacts/mnist10k/dataset_verification.json').read_text())
        assert digest(X)==previous['x_sha256'] and digest(y)==previous['y_sha256']
        metadata['fixed_subset_seed']=42
        for name in ['selected_corpus_indices.npy','source_manifest.json']:
            source=Path('/workspace/artifacts/mnist10k')/name
            (data_out/name).write_bytes(source.read_bytes())
    np.save(cache/'raw.npy',np.asarray(X,dtype=float))
    np.save(cache/'standard.npy',StandardScaler().fit_transform(np.asarray(X,dtype=float)))
    np.save(cache/'minmax.npy',MinMaxScaler().fit_transform(np.asarray(X,dtype=float)))
    np.save(cache/'y.npy',y)
    if kind=='synthetic':
        public=(X-np.asarray(metadata['public_center']))/np.asarray(metadata['public_scale'])
        norms=np.linalg.norm(public,axis=1)
        clipped=public*np.minimum(1.,4./np.maximum(norms,1e-12))[:,None]
        dp_public=dict(source=metadata['public_reference_note'],private_data_fitted_scaler=False,
                       clipped_record_fraction_trusted_only=float(np.mean(norms>4)))
    else:
        clipped,dp_public=clipped_public_features(X,dataset,4.)
    np.save(cache/'clipped.npy',clipped)
    np.savez_compressed(data_out/'dataset.npz',X=X,y=y)
    verification=dict(dataset_name=dataset,shape=list(X.shape),n_classes=len(np.unique(y)),
        class_counts=np.bincount(y).tolist(),finite=True,x_sha256=digest(X),y_sha256=digest(y),
        fixed_dataset_across_repetitions=True,metadata=metadata,dp_public_preprocessing=dp_public)
    dump(data_out/'verification.json',verification)
    for repeat,seed in enumerate(seeds,1):
        name=f'{kind}{repeat}'; directory=OUT/name
        for subdir in ['raw','predictions','logs']:(directory/subdir).mkdir(parents=True,exist_ok=True)
        parts={}
        for key,mode,alpha in [('iid','iid',.5),('strong','dirichlet',.1),('medium','dirichlet',.5),
                               ('weak','dirichlet',5.),('quantity','quantity_skew',.5),('label','label_limited',.5)]:
            part=make_partition(mode,len(X),10,seed,y,alpha=alpha,min_samples_per_client=3,labels_per_client=2)
            assert np.array_equal(np.sort(np.concatenate(part)),np.arange(len(X)))
            parts[key]=dict(mode=mode,alpha=alpha,indices=[i.tolist() for i in part],
                sizes=[len(i) for i in part],class_counts=partition_class_counts(part,y),
                fingerprint=partition_fingerprint(part),heterogeneity=measure_partition_heterogeneity(part,y))
        dump(directory/'partitions.json',parts)
        config=dict(series=name,dataset_name=dataset,seed=seed,repetition=repeat,
            n_samples=len(X),n_features=X.shape[1],n_classes=len(np.unique(y)),
            num_clients=10,rounds=20,tol=1e-4,max_iter=300,dp_delta=1e-5,dp_clip_norm=4.,
            data_cache=str(cache),data_archive_path=f'datasets/{dataset}/dataset.npz',
            data_verification=verification,
            randomness_note='Benchmark seed controls algorithms, partitions and availability. DP noise uses OS-backed randomness and is intentionally not seeded.',
            execution_resources=dict(concurrent_lanes=2,cpus_per_lane=2,blas_threads=2,
                flower_cpus=2,flower_object_store_bytes=268435456,
                worker_imports_reused=True,flower_ray_runtime_reused=True,
                flower_stateless_workers_reused=True,
                client_factory_transport='Ray object store once per simulation; ObjectRef resolved in each actor call',
                flower_state='New server, model parameters, Context and ClientApp each simulation; client_fn creates a NumPyClient for each message. Stateless actor processes reused; no pending tasks at run boundaries.',
                flower_timing_note='Ray and actor infrastructure initialization recorded separately; runtime_sec measures simulation using initialized workers.',
                timings_note='Runs execute concurrently on disjoint two-CPU affinity sets; shared memory and host resources can still affect wall time.'))
        dump(directory/'protocol.json',config)
        jobs=[]
        def add(scenario,**kw):
            for i,a in enumerate(ALGORITHMS):
                jobs.append(dict(id=f'{scenario}_{i}',scenario=scenario,algorithm=a,seed=seed,series=name,**kw))
        for i,a in enumerate(['agglomerative','dbscan','gmm','kmeans']):
            jobs.append(dict(id=f'baseline_{i}',scenario='baseline',algorithm=a,local=True,seed=seed,series=name))
        for p in ['iid','strong','quantity','label']:
            for tag,participation,dropout in [('full',1.,0.),('p80',.8,0.),('d20',1.,.2),('p50d20',.5,.2)]:
                add(f'{p}_{tag}',partition=p,participation=participation,dropout=dropout)
        for p in ['medium','weak']:add(f'{p}_full',partition=p,participation=1.,dropout=0.)
        for epsilon in [20,10,5,1]:add(f'dp{epsilon}',partition='iid',participation=1.,dropout=0.,epsilon=epsilon)
        assert len(jobs)==180
        dump(directory/'experiment_plan.json',jobs)
        print('PREPARED',name,'seed',seed,'shape',X.shape,flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('datasets',nargs='*',choices=list(SEEDS))
    args=parser.parse_args()
    for kind in args.datasets or list(SEEDS):prepare(kind)
