"""Fresh job state with cached imports on two disjoint CPU affinity sets."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import threading
import time

ROOT=Path(__file__).resolve().parent
OUT=Path('/workspace/artifacts/benchmark_3x3_20261028')
PYTHON='/workspace/.review/flower-venv/bin/python'
cpus=sorted(os.sched_getaffinity(0)); assert len(cpus)>=4
names=['drybean1','mnist1','synthetic1','drybean2','mnist2','synthetic2','drybean3','mnist3','synthetic3']
jobs=[j for name in names for j in json.loads((OUT/name/'experiment_plan.json').read_text())]
assert len(jobs)==1620
lock=threading.Lock(); cursor=iter(enumerate(jobs,1)); completed=0

def run_lane(lane):
    global completed
    env=os.environ.copy(); env.update(OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2',
        MPLBACKEND='Agg',PYTHONPATH='/workspace/PyClustEval',FLWR_TELEMETRY_ENABLED='0',
        MPLCONFIGDIR='/workspace/.cache/matplotlib',XDG_CACHE_HOME='/workspace/.cache',BENCH_LANE=str(lane))
    affinity=','.join(map(str,cpus[lane*2:lane*2+2]))
    worker=None
    while True:
        with lock:
            try:number,job=next(cursor)
            except StopIteration:break
        directory=OUT/job['series']; result=directory/'raw'/(job['id']+'.json')
        if result.exists():
            recorded=json.loads(result.read_text())
            if recorded.get('status')=='ok' and ('flower' not in job['algorithm'] or
                    recorded.get('execution_profile')=='warm_stateless_actor_pool_cached_factory_v1'):
                with lock:completed+=1
                continue
        if worker is None or worker.poll() is not None:
            worker=subprocess.Popen(['taskset','-c',affinity,PYTHON,str(ROOT/'worker.py'),'--serve'],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                text=True,bufsize=1,cwd='/workspace/PyClustEval',env=env,start_new_session=True)
        print(datetime.now(timezone.utc).isoformat(),f'[{number}/1620] lane={lane} START',
              job['series'],job['id'],job['algorithm'],flush=True)
        worker.stdin.write(json.dumps(job)+'\n'); worker.stdin.flush()
        deadline=time.monotonic()+(1800 if job['algorithm']=='gmm' else 900)
        code=99
        while time.monotonic()<deadline:
            ready,_,_=select.select([worker.stdout],[],[],min(5,max(0,deadline-time.monotonic())))
            if not ready:
                if worker.poll() is not None:break
                continue
            line=worker.stdout.readline()
            if not line:break
            if line.startswith('BENCHMARK_RESULT '):
                event=json.loads(line[len('BENCHMARK_RESULT '):]);code=event['code'];break
            print('WORKER_STARTUP',lane,line.rstrip(),flush=True)
        else:
            code=124
            result.write_text(json.dumps(dict(job=job,status='timeout',error='Time limit reached; no metrics invented'),indent=2))
        if code in [99,124]:
            try:os.killpg(worker.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            worker.wait();worker=None
        with lock:
            completed+=1
            print(datetime.now(timezone.utc).isoformat(),f'[{completed}/1620] lane={lane} END',
                  job['series'],job['id'],'exit',code,flush=True)
            (ROOT/'progress.json').write_text(json.dumps(dict(completed=completed,total=1620,
                last_series=job['series'],last_job=job['id'],last_exit=code,updated_at=datetime.now(timezone.utc).isoformat())))
    if worker is not None:
        worker.stdin.close()
        try:worker.wait(timeout=30)
        except subprocess.TimeoutExpired:os.killpg(worker.pid,signal.SIGKILL);worker.wait()

with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run_lane,[0,1]))
print('ALL JOBS FINISHED',len(jobs),flush=True)
