"""Run one actual adapter job in an isolated process; record exact UTC times."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys
import time
import traceback

os.environ.setdefault('MPLCONFIGDIR','/workspace/.cache/matplotlib')
os.environ.setdefault('XDG_CACHE_HOME','/workspace/.cache')
sys.path.insert(0,'/workspace/PyClustEval')
import numpy as np
from clustering_eval.algorithms.registry import default_registry
from clustering_eval.application.comparison_service import METRICS
from clustering_eval.default_profile import defaults_for
from clustering_eval.federated.environment import make_participation_schedule
from clustering_eval.metrics.clustering import compute_metrics
from clustering_eval.metrics.diagnostics import prediction_fingerprint
from clustering_eval.privacy.aggregate_dp import make_dp_aggregate_config
from clustering_eval.results.history_store import _strict_json_value

OUT=Path('/workspace/artifacts/benchmark_3x3_20261028')
_real_ray_shutdown = None
_original_flower_run_simulation = None
_ray_pool = None

def prepare_reusable_ray():
    """Reuse stateless workers; each simulation has a new ClientApp/factory."""
    global _real_ray_shutdown, _ray_pool
    import ray
    from flwr.server.superlink.fleet.vce.backend.raybackend import RayBackend
    from flwr.simulation.ray_transport.ray_actor import BasicActorPool, ClientAppActor
    if _real_ray_shutdown is None:
        _real_ray_shutdown = ray.shutdown
        def terminate_pool_only(self):
            if self.pool is not None:
                assert not self.pool._future_to_actor, 'unfinished tasks must not carry between runs'
        def use_stateless_pool(self, app_fn):
            assert _ray_pool is not None and not _ray_pool._future_to_actor
            assert len(_ray_pool.pool) == _ray_pool.num_actors == 2
            self.pool = _ray_pool
            # Ray resolves a top-level ObjectRef before Actor.run. Store the
            # immutable factory once instead of serializing its full MNIST
            # closure again for every client message.
            self.app_fn = ray.put(app_fn)
        RayBackend.terminate = terminate_pool_only
        RayBackend.build = use_stateless_pool
    if not ray.is_initialized():
        _ray_pool = None
        pythonpath = os.pathsep.join(sys.path)
        os.environ['PYTHONPATH'] = pythonpath
        ray.init(num_cpus=2, include_dashboard=False, object_store_memory=256*1024*1024,
                 _temp_dir=f'/tmp/ray-benchmark-{os.environ.get("BENCH_LANE","0")}',
                 runtime_env={'env_vars': {'PYTHONPATH': pythonpath}})
    if _ray_pool is None:
        _ray_pool = BasicActorPool(ClientAppActor, {'num_cpus': 1., 'num_gpus': 0.}, {})
        _ray_pool.add_actors_to_pool(2)
        ray.get([actor.__ray_ready__.remote() for actor in _ray_pool.pool])

def execute(job):
    global _original_flower_run_simulation
    directory=OUT/job['series']; seed=job['seed']
    config=json.loads((directory/'protocol.json').read_text()); cache=Path(config['data_cache'])
    row=dict(job=job,status='started',input_shape=[config['n_samples'],config['n_features']],
             started_at=datetime.now(timezone.utc).isoformat(),cpu_affinity=sorted(os.sched_getaffinity(0)))
    started=time.monotonic()
    try:
        alg=default_registry().get(job['algorithm'])
        y=np.load(cache/'y.npy'); X_eval=np.load(cache/'standard.npy',mmap_mode='r')
        parts=json.loads((directory/'partitions.json').read_text())
        pdata=parts[job.get('partition','iid')]
        partition=None if job.get('local') else [np.asarray(p,dtype=int) for p in pdata['indices']]
        if partition is not None:
            assert np.array_equal(np.sort(np.concatenate(partition)),np.arange(len(y)))
        k=config['n_classes']
        params=dict(k=k,n_clusters=k,rounds=20,tol=1e-4,max_iter=300,
                    density_min_samples=5,client_cpus=1.,client_gpus=0.)
        params.update(alg.default_params); params.update(defaults_for(job['algorithm']))
        schedule=[]
        if partition is not None:
            schedule=make_participation_schedule(num_clients=10,rounds=20,
                participation_rate=job.get('participation',1.),dropout_rate=job.get('dropout',0.),seed=seed)
            params['participation_schedule']=schedule
        if 'epsilon' in job:
            kind='fuzzy' if 'fuzzy' in job['algorithm'] else 'gmm' if 'gmm' in job['algorithm'] else 'kmeans'
            params['dp_aggregate']=make_dp_aggregate_config(kind=kind,epsilon=job['epsilon'],delta=1e-5,
                clip_norm=4.,rounds=20 if job['algorithm'] in ('Adapted FKM','fed_kmeans_flower',
                    'fed_fuzzy_cmeans_flower','fed_gmm_diag_flower') else 1,enabled=True)
            mode='clipped'
        else:mode=getattr(alg,'input_preprocessing','standard')
        X=np.load(cache/(('raw' if mode in ('none','raw') else mode)+'.npy'),mmap_mode='r')
        assert list(X.shape)==row['input_shape']
        if 'flower' in job['algorithm']:
            import flwr.simulation
            setup_begin=time.monotonic()
            prepare_reusable_ray()
            row['flower_infrastructure_setup_sec']=time.monotonic()-setup_begin
            row['execution_profile']='warm_stateless_actor_pool_cached_factory_v1'
            row['flower_lifecycle']='Reused stateless Ray actors; new ClientApp and immutable factory per simulation, stored as a Ray ObjectRef; client_fn creates a NumPyClient for each message; fresh server, Context, parameters and schedule for each job. Empty in-flight task map asserted at every boundary.'
            if _original_flower_run_simulation is None:
                _original_flower_run_simulation=flwr.simulation.run_simulation
            original=_original_flower_run_simulation
            def limited(**kw):
                kw['backend_config']['init_args']={'num_cpus':2,'include_dashboard':False,
                    'object_store_memory':256*1024*1024,'_temp_dir':f'/tmp/ray-benchmark-{os.environ.get("BENCH_LANE","0")}'}
                return original(**kw)
            flwr.simulation.run_simulation=limited
        begin=time.monotonic(); result=alg.run(X,partition,params,seed)
        row['algorithm_wall_sec']=time.monotonic()-begin
        labels=np.asarray(result.labels); assert labels.shape==y.shape
        np.savez_compressed(directory/'predictions'/(job['id']+'-labels.npz'),labels=labels)
        row.update(status='ok',runtime_sec=result.runtime_sec,communication_bytes=result.communication_bytes,
            rounds=result.model_state.get('rounds','—'),
            backend=result.model_state.get('backend','local' if job.get('local') else 'custom'),
            prediction_hash=prediction_fingerprint(labels),cluster_count=len(set(labels.tolist())-{-1}),
            noise_fraction=float(np.mean(labels==-1)),metrics=compute_metrics(X_eval,y,labels,list(METRICS)),
            model_state=result.model_state,history=result.history,params=params,
            partition_hash=pdata['fingerprint'] if partition is not None else None,
            client_sizes=pdata['sizes'] if partition is not None else [],schedule=schedule,
            preprocessing=mode)
    except Exception as exc:
        row.update(status='error',error=f'{type(exc).__name__}: {exc}',traceback=traceback.format_exc())
        traceback.print_exc()
        if _real_ray_shutdown is not None:
            _real_ray_shutdown()
    row['total_wall_sec']=time.monotonic()-started
    row['finished_at']=datetime.now(timezone.utc).isoformat()
    path=directory/'raw'/(job['id']+'.json'); temporary=path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(_strict_json_value(row),ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    temporary.replace(path)
    print('RESULT',job['series'],job['id'],row['status'],row.get('metrics'),row['total_wall_sec'],flush=True)
    return 0 if row['status']=='ok' else 1

if __name__ == '__main__':
    if sys.argv[1:] != ['--serve']:
        sys.exit(execute(json.loads(sys.argv[1])))
    import gc
    control = os.fdopen(os.dup(1), 'w', buffering=1)
    original_pythonpath = os.environ.get('PYTHONPATH', '')
    for command in sys.stdin:
        job = json.loads(command)
        log_path = OUT / job['series'] / 'logs' / (job['id'] + '.log')
        sys.stdout.flush(); sys.stderr.flush()
        with log_path.open('w') as log:
            os.dup2(log.fileno(), 1); os.dup2(log.fileno(), 2)
        os.environ['PYTHONPATH'] = original_pythonpath
        try:
            code = execute(job)
        except BaseException:
            traceback.print_exc(); code = 99
        sys.stdout.flush(); sys.stderr.flush()
        gc.collect()
        control.write('BENCHMARK_RESULT ' + json.dumps(dict(code=code, job=job['id'], series=job['series'])) + '\n')
        control.flush()
    if _real_ray_shutdown is not None:
        _real_ray_shutdown()
