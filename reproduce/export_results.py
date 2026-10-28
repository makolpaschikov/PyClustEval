"""Validate and export the nine completed series without rerunning algorithms."""
from __future__ import annotations
from collections import OrderedDict, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED
from zoneinfo import ZoneInfo

sys.path.insert(0,'/workspace/PyClustEval')
import numpy as np
from clustering_eval.application import HistoryQueryService, RunRequest
from clustering_eval.application.dto import AlgorithmRunReport, ComparisonReport, PartitionReport
from clustering_eval.metrics.clustering import METRIC_SCHEMA_VERSION, silhouette_reference_indices
from clustering_eval.metrics.diagnostics import active_data_diagnostics, array_fingerprint, client_external_metrics, prediction_fingerprint
from clustering_eval.default_profile import PROFILE_NAME, defaults_for
from clustering_eval.algorithms.registry import default_registry
from clustering_eval.results.history_store import HistoryStore, _strict_json_value

ROOT=Path(__file__).resolve().parent
SOURCE=Path('/workspace/artifacts/benchmark_3x3_20261028')
DEST=Path('/workspace/artifacts/benchmark_3x3_results_20261028')
REPO=Path('/workspace/PyClustEval')
NAMES=['drybean1','drybean2','drybean3','mnist1','mnist2','mnist3','synthetic1','synthetic2','synthetic3']
METRICS=['ari','ami','nmi','silhouette','davies_bouldin','calinski_harabasz']

def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(_strict_json_value(value),ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(1024*1024):h.update(block)
    return h.hexdigest()

def write_csv(path,rows):
    keys=list(rows[0])
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader();writer.writerows(rows)

def app_time(value):
    # The existing UI writes naive local datetimes and sorts them directly.
    # Keep its file format compatible; exact aware UTC values remain in source_run.
    return datetime.fromisoformat(value).astimezone(ZoneInfo('Europe/Moscow')).replace(tzinfo=None)

def main():
    code_check=json.loads((ROOT/'source_code_verification.json').read_text())
    current_patch=subprocess.check_output(['git','diff','--binary'],cwd=REPO)
    assert hashlib.sha256(current_patch).hexdigest()==code_check['working_tree_patch_sha256'],'Application source changed during the benchmark'
    assert not DEST.exists(),'Export destination must be absent to avoid stale mixed histories'
    DEST.mkdir()
    manifest=dict(format='pyclusteval.three-datasets-three-seeds.v1',
        exported_at=datetime.now(timezone.utc).isoformat(),run_count=1620,comparison_count=207,
        series_count=9,series=[],
        common_protocol=dict(clients=10,round_budget=20,tol=1e-4,max_iter=300,
            dirichlet_alphas=[.1,.5,5.],availability_pairs=[[1,0],[.8,0],[1,.2],[.5,.2]],
            dp_epsilons=[20,10,5,1],dp_delta=1e-5,dp_clip_norm=4,
            representation='All original features; no PCA or subsampling of the selected datasets',
            dataset_repetitions='Fixed data within each dataset; different pre-registered algorithm/partition/availability seeds',
            dp_randomness='OS-backed random noise, not fixed by benchmark seeds'),
        source_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip())
    all_flat=[]; all_run_ids=set(); total_loaded=0; array_hashes={}
    registry=default_registry()
    environment=dict(python=sys.version.split()[0],numpy=np.__version__,
        sklearn=importlib.metadata.version('scikit-learn'),scipy=importlib.metadata.version('scipy'),
        platform=platform.platform(),machine=platform.machine())
    shutil.copytree(SOURCE/'datasets',DEST/'datasets')
    for name in NAMES:
        source=SOURCE/name; dest=DEST/name;dest.mkdir()
        protocol=json.loads((source/'protocol.json').read_text())
        plan=json.loads((source/'experiment_plan.json').read_text())
        assert len(plan)==180
        parts=json.loads((source/'partitions.json').read_text())
        y=np.load(Path(protocol['data_cache'])/'y.npy')
        if protocol['dataset_name'] not in array_hashes:
            hashes={mode:array_fingerprint(np.load(Path(protocol['data_cache'])/(mode+'.npy'),mmap_mode='r'))
                    for mode in ['raw','standard','clipped']}
            array_hashes[protocol['dataset_name']]=hashes
        hashes=array_hashes[protocol['dataset_name']]
        silhouette_reference=silhouette_reference_indices(len(y))
        expected_shape=[protocol['n_samples'],protocol['n_features']]
        for p in parts.values():
            ids=np.concatenate(p['indices'])
            assert np.array_equal(np.sort(ids),np.arange(len(y)))
            assert sum(p['sizes'])==len(y)
        for f in ['protocol.json','experiment_plan.json','partitions.json']:shutil.copy2(source/f,dest/f)
        shutil.copytree(source/'predictions',dest/'predictions')
        shutil.copytree(source/'logs',dest/'logs')
        if (source/'attempts').exists():shutil.copytree(source/'attempts',dest/'attempts')
        groups=OrderedDict()
        for job in plan:
            file=source/'raw'/(job['id']+'.json'); row=json.loads(file.read_text())
            assert row['status']=='ok',(name,job['id'],row.get('error'))
            assert row['job']==job and row['input_shape']==expected_shape
            if 'flower' in job['algorithm']:
                assert row['execution_profile']=='warm_stateless_actor_pool_cached_factory_v1'
                # Clarify transport metadata independently of benchmark values.
                row['flower_lifecycle']=protocol['execution_resources']['flower_state']
            assert job['seed']==protocol['seed']
            groups.setdefault(job['scenario'],[]).append((job,row,file))
        assert len(groups)==23
        store=HistoryStore(dest/'history')
        summary=dict(format='pyclusteval.benchmark-series.v1',series=name,
            dataset_name=protocol['dataset_name'],seed=protocol['seed'],
            n_samples=len(y),n_features=protocol['n_features'],n_classes=protocol['n_classes'],
            run_count=180,comparison_count=23,protocol=protocol,
            history_note='Exact original adapter history; empty history means no trace was recorded. Global ARI/AMI/NMI were measured at the end, not after every round.',
            timestamps_note='Exact UTC timestamps recorded by each worker. Comparison dates span grouped workers; individual measured algorithm times are preserved.',
            experiments=[],runs=[])
        flat=[]
        for scenario,entries in groups.items():
            first_job,first_row,_=entries[0];local=bool(first_job.get('local'))
            p=None if local else parts[first_job['partition']]
            partition=None if local else [np.asarray(ids) for ids in p['indices']]
            active={} if local else active_data_diagnostics(partition,first_row['schedule'])
            privacy='gaussian_dp_aggregate' if 'epsilon' in first_job else 'none'
            request=RunRequest(mode='local' if local else 'federated',dataset_name=protocol['dataset_name'],
                algorithms=tuple(j['algorithm'] for j,_,_ in entries),seed=protocol['seed'],num_clients=10,
                partition_mode='iid' if local else p['mode'],dirichlet_alpha=.5 if local else p['alpha'],
                target_clusters=protocol['n_classes'],rounds=20,tol=1e-4,max_iter=300,
                participation_rate=first_job.get('participation',1.),dropout_rate=first_job.get('dropout',0.),
                privacy_mode=privacy,dp_epsilon=first_job.get('epsilon',5.),dp_delta=1e-5,dp_clip_norm=4.,
                algorithm_params_by_name={j['algorithm']:{k:v for k,v in row['params'].items()
                    if k not in ['participation_schedule','dp_aggregate']} for j,row,_ in entries})
            request.validate()
            partition_report=None if local else PartitionReport(mode=p['mode'],num_clients=10,
                client_sample_counts=p['sizes'],fingerprint=p['fingerprint'],
                dirichlet_alpha=p['alpha'] if p['mode']=='dirichlet' else None,
                client_class_counts=p['class_counts'],labels_per_client=2 if p['mode']=='label_limited' else None,
                participation_rate=request.participation_rate,dropout_rate=request.dropout_rate,
                round_schedule=first_row['schedule'],heterogeneity=p['heterogeneity'])
            privacy_report=dict(mode=privacy,end_to_end_report_is_dp=False,
                report_scope='trusted central benchmark evaluator',epsilon_total=first_job.get('epsilon'),
                delta=1e-5 if privacy!='none' else None,clip_norm=4 if privacy!='none' else None,
                public_preprocessing=protocol['data_verification']['dp_public_preprocessing'])
            results=[];logs=['Export of original completed benchmark workers; no algorithms rerun.\n',summary['timestamps_note']+'\n']
            for job,row,file in entries:
                key=(name,job['id']);assert key not in all_run_ids;all_run_ids.add(key)
                with np.load(source/'predictions'/(job['id']+'-labels.npz')) as z:labels=z['labels']
                assert labels.shape==(len(y),)
                assert prediction_fingerprint(labels)==row['prediction_hash']
                assert row['cluster_count']==len(set(labels.tolist())-{-1})
                assert row['noise_fraction']==float(np.mean(labels==-1))
                if p is not None:
                    assert row['partition_hash']==p['fingerprint']
                    assert row['schedule']==first_row['schedule']
                origin={k:row[k] for k in ['started_at','finished_at','total_wall_sec','algorithm_wall_sec','cpu_affinity']}
                origin.update(run_id=job['id'],series=name,seed=job['seed'],source_json_sha256=sha(file),
                    prediction_file='predictions/'+job['id']+'-labels.npz',
                    client_metrics_origin='post-hoc from the stored predictions')
                for k in ['execution_profile','flower_lifecycle','flower_infrastructure_setup_sec']:
                    if k in row:origin[k]=row[k]
                state=dict(row['model_state'])
                assert not {'benchmark','source_run','diagnostics'}.intersection(state)
                state['source_run']=origin
                state['benchmark']=dict(seed=job['seed'],target_clusters=protocol['n_classes'],
                    requested_target_clusters=protocol['n_classes'],cluster_count_mode='known_k',
                    cluster_count_source='pre-registered public class count',tuning_mode='none',
                    parameter_tuning_mode='none',parameter_profile=PROFILE_NAME,
                    profile_defaults=defaults_for(job['algorithm']),environment=environment,
                    round_budget=20,requested_common_round_budget=20,
                    tol=1e-4,max_iter=300,density_min_samples=5,
                    num_clients=None if local else 10,partition_mode=None if local else p['mode'],
                    min_samples_per_client=None if local else 3,
                    participation_rate=None if local else request.participation_rate,
                    dropout_rate=None if local else request.dropout_rate,
                    dp_epsilon=first_job.get('epsilon'),dp_delta=1e-5 if privacy!='none' else None,
                    dp_clip_norm=4. if privacy!='none' else None,
                    evaluation_space='StandardScaler(original_raw_X)',effective_params=row['params'],
                    benchmark_input_hash=hashes['clipped' if privacy!='none' else 'raw'],
                    evaluation_input_hash=hashes['standard'],
                    preprocessing=row['preprocessing'],metric_schema_version=METRIC_SCHEMA_VERSION,
                    common_param_support=list(getattr(registry.get(job['algorithm']),'common_param_support',())),
                    external_metric_population='all records; -1 is one predicted label',
                    internal_metric_population='assigned non-noise records; silhouette fixed 2000-record reference',
                    privacy_mode=privacy,privacy_report=privacy_report,
                    communication_scope='logical_payload_only_not_network_wire_bytes',
                    active_data_fingerprint=active.get('active_data_fingerprint'),
                    round_active_data=active.get('rounds',[]),
                    dataset_source_metadata=protocol['data_verification']['metadata'])
                assigned=labels!=-1;_,counts=np.unique(labels[assigned],return_counts=True)
                dominant=float(counts.max()/counts.sum()) if len(counts) else 0.
                state['diagnostics']=dict(prediction_hash=row['prediction_hash'],
                    cluster_count_excluding_noise=row['cluster_count'],noise_fraction=row['noise_fraction'],
                    assigned_fraction=1.-row['noise_fraction'],dominant_cluster_fraction=dominant,
                    degenerate=row['cluster_count']<2,near_degenerate=row['cluster_count']>=2 and dominant>=.95,
                    low_coverage=1.-row['noise_fraction']<.5,metric_schema_version=METRIC_SCHEMA_VERSION,
                    silhouette_reference_sample_count=len(silhouette_reference),
                    silhouette_assigned_sample_count=int(np.sum(labels[silhouette_reference]!=-1)),
                    silhouette_reference_hash=array_fingerprint(silhouette_reference),
                    raw_prediction_hash=array_fingerprint(np.asarray(labels,dtype=np.int64)),
                    runtime_algorithm_call_sec=row['algorithm_wall_sec'],
                    runtime_reported_by_algorithm_sec=row['runtime_sec'],
                    client_metrics=client_external_metrics(y,labels,partition))
                proxy=bool(state.get('not_equivalent_to_author_original'))
                result=AlgorithmRunReport(algorithm=job['algorithm']+(' [DP proxy]' if proxy else ''),
                    backend='author-server DP proxy' if proxy else row['backend'],runtime_sec=row['runtime_sec'],
                    communication_bytes=row['communication_bytes'],rounds=row['rounds'],
                    **row['metrics'],model_state=state,history=row['history'])
                results.append(result)
                summary['runs'].append({**{k:v for k,v in row.items() if k not in ['model_state','history']},
                    'display_algorithm':result.algorithm,'history_length':len(row['history']),
                    'source_run':origin})
                record=dict(series=name,dataset=protocol['dataset_name'],seed=job['seed'],scenario=scenario,
                    run_id=job['id'],algorithm=job['algorithm'],display_algorithm=result.algorithm,
                    backend=row['backend'],status=row['status'],n_samples=len(y),n_features=protocol['n_features'],
                    partition_mode=None if local else p['mode'],alpha=None if local else p['alpha'],
                    partition_fingerprint=None if local else p['fingerprint'],
                    class_js_divergence_weighted_bits=None if local else p['heterogeneity'].get('class_js_divergence_weighted_bits'),
                    client_size_cv=None if local else p['heterogeneity']['size_cv'],
                    active_data_fingerprint=active.get('active_data_fingerprint'),
                    participation_rate=job.get('participation'),dropout_rate=job.get('dropout'),
                    privacy_mode=privacy,epsilon=job.get('epsilon'),
                    runtime_sec=row['runtime_sec'],algorithm_wall_sec=row['algorithm_wall_sec'],
                    communication_bytes=row['communication_bytes'],rounds=row['rounds'],
                    cluster_count=row['cluster_count'],noise_fraction=row['noise_fraction'],
                    history_length=len(row['history']),prediction_hash=row['prediction_hash'],
                    **row['metrics'],started_at=row['started_at'],finished_at=row['finished_at'])
                flat.append(record);all_flat.append(record)
                logs.extend(['\n===== '+job['id']+' =====\n',
                    re.sub(r'\x1b\[[0-9;]*m','',(source/'logs'/(job['id']+'.log')).read_text())+'\n'])
            report=ComparisonReport(experiment_id=name+'_'+scenario,
                started_at=min(app_time(r['started_at']) for _,r,_ in entries),
                finished_at=max(app_time(r['finished_at']) for _,r,_ in entries),
                request=request,dataset_display_name=protocol['dataset_name'],n_samples=len(y),
                n_features=protocol['n_features'],results=results,partition=partition_report,
                privacy_report=privacy_report,log_lines=logs)
            directory=store.save(report)
            payload=json.loads((directory/'report.json').read_text())
            payload['history_directory']='history/'+directory.name
            payload['export_provenance']=dict(source_scenario=scenario,exact_worker_timestamps=True,
                source_run_ids=[j['id'] for j,_,_ in entries],exported_without_rerun=True,
                native_datetime_timezone='Europe/Moscow',exact_utc_timestamps_location='results[*].model_state.source_run')
            dump(directory/'report.json',payload)
            for r in summary['runs'][-len(entries):]:r['history_report']='history/'+directory.name+'/report.json'
            summary['experiments'].append(dict(scenario=scenario,history_key=directory.name,
                history_report='history/'+directory.name+'/report.json',request=asdict(request)))
        query=HistoryQueryService(dest/'history');items=query.list_experiments();assert len(items)==23
        for exp in summary['experiments']:
            loaded=query.get_experiment(exp['history_key']);entries=groups[exp['scenario']]
            assert len(loaded.results)==len(entries)
            assert loaded.n_samples==len(y) and loaded.n_features==protocol['n_features']
            assert loaded.seed==protocol['seed'] and loaded.dataset_name==protocol['dataset_name']
            for result,(_,row,_) in zip(loaded.results,entries):
                assert result.metrics_dict()==row['metrics'] and result.history==row['history']
                assert result.runtime_sec==row['runtime_sec'] and result.rounds==row['rounds']
                assert result.communication_bytes==row['communication_bytes']
                assert all(result.model_state[k]==v for k,v in row['model_state'].items())
                total_loaded+=1
        dump(dest/'report.json',summary);write_csv(dest/'results.csv',flat)
        manifest['series'].append(dict(name=name,dataset=protocol['dataset_name'],seed=protocol['seed'],
            n_samples=len(y),n_features=protocol['n_features'],n_classes=protocol['n_classes'],
            run_count=len(flat),comparison_count=23,path=name))
        print('EXPORTED',name,'runs',len(flat),'history comparisons',len(items),flush=True)
    assert len(all_flat)==len(all_run_ids)==total_loaded==1620
    write_csv(DEST/'all_results.csv',all_flat)
    aggregate=[];grouped=defaultdict(list)
    for row in all_flat:grouped[row['dataset'],row['scenario'],row['algorithm']].append(row)
    for (dataset,scenario,algorithm),rows in sorted(grouped.items()):
        assert len(rows)==3 and len({r['seed'] for r in rows})==3
        row=dict(dataset=dataset,scenario=scenario,algorithm=algorithm,repetitions=3,
                 seeds=','.join(str(r['seed']) for r in rows))
        for metric in METRICS+['runtime_sec','communication_bytes','cluster_count','noise_fraction',
                               'class_js_divergence_weighted_bits','client_size_cv']:
            values=[r[metric] for r in rows if r[metric] is not None]
            row[metric+'_valid_n']=len(values)
            row[metric+'_mean']=float(np.mean(values)) if values else None
            row[metric+'_std']=float(np.std(values,ddof=1)) if len(values)>1 else None
            row[metric+'_min']=min(values) if values else None
            row[metric+'_max']=max(values) if values else None
        aggregate.append(row)
    write_csv(DEST/'aggregate_by_dataset.csv',aggregate)
    assert len(aggregate)==540
    assert len({s['seed'] for s in manifest['series']})==9
    shutil.copy2(ROOT/'merge_history.py',DEST/'merge_history.py')
    rep=DEST/'reproduce';rep.mkdir()
    for name in ['prepare.py','worker.py','run_persistent.py','export_results.py',
                 'runtime_reuse_verification.json','history_compatibility_verification.json','drybean_source.json']:
        if (ROOT/name).exists():shutil.copy2(ROOT/name,rep/name)
    shutil.copy2(ROOT/'source_code_verification.json',rep/'source_code_verification.json')
    (rep/'source_changes.patch').write_bytes(subprocess.check_output(['git','diff','--binary'],cwd=REPO))
    with ZipFile(rep/'source_snapshot.zip','w',ZIP_DEFLATED,compresslevel=6) as z:
        tracked=subprocess.check_output(['git','ls-files','-z','--','clustering_eval'],cwd=REPO).split(b'\0')
        for name in tracked:
            if not name:continue
            f=REPO/name.decode()
            if f.is_file() and not f.is_symlink():z.write(f,f.relative_to(REPO).as_posix())
        for name in ['pyproject.toml','README.md','pyclusteval_ui.py']:
            z.write(REPO/name,name)
    versions={d.metadata['Name']:d.version for d in importlib.metadata.distributions() if d.metadata['Name']}
    dump(rep/'environment.json',dict(python=sys.version,platform=platform.platform(),packages=versions))
    (DEST/'README.md').write_text(README)
    dump(DEST/'manifest.json',manifest)
    verification=dict(successful_runs=1620,series=9,comparisons=207,native_history_loaded_results=total_loaded,
        exact_metrics_preserved=True,exact_round_history_preserved=True,exact_model_states_preserved=True,
        all_prediction_fingerprints_valid=True,all_partition_indices_cover_full_dataset=True,
        distinct_pre_registered_seeds=[s['seed'] for s in manifest['series']],
        undefined_metrics='JSON null; not replaced with zero',all_source_worker_timestamps_exact=True)
    dump(DEST/'verification.json',verification)
    files=[]
    for path in sorted(DEST.rglob('*')):
        if path.is_file():files.append(dict(path=path.relative_to(DEST).as_posix(),bytes=path.stat().st_size,sha256=sha(path)))
    dump(DEST/'checksums.json',dict(algorithm='sha256',files=files))
    archive=DEST.parent/'benchmark_3datasets_3seeds_20261028.zip'
    with ZipFile(archive,'w',ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
        for f in sorted(DEST.rglob('*')):
            if f.is_file():z.write(f,f.relative_to(DEST).as_posix())
        assert z.testzip() is None
    print('DONE',archive,archive.stat().st_size,'bytes',sha(archive),flush=True)

README='''# Девять серий экспериментов: Dry Bean, MNIST 10k, синтетика

В архиве находятся фактически выполненные 1 620 прогонов алгоритмов:
9 серий × 180 прогонов. Каждая серия содержит 23 сравнения: одно сравнение
четырёх локальных алгоритмов и 22 сценария по восьми федеративным алгоритмам.

| Папка | Датасет | Seed | Размер |
|---|---|---:|---|
| drybean1 | Dry Bean | 17 | 13 611 × 16 |
| drybean2 | Dry Bean | 43 | 13 611 × 16 |
| drybean3 | Dry Bean | 101 | 13 611 × 16 |
| mnist1 | MNIST 10k | 211 | 10 000 × 784 |
| mnist2 | MNIST 10k | 307 | 10 000 × 784 |
| mnist3 | MNIST 10k | 401 | 10 000 × 784 |
| synthetic1 | Anisotropic mixture | 503 | 12 000 × 24 |
| synthetic2 | Anisotropic mixture | 601 | 12 000 × 24 |
| synthetic3 | Anisotropic mixture | 709 | 12 000 × 24 |

## Что находится в каждой папке

- `report.json`: сводный JSON по 180 запускам с параметрами и ссылками на историю.
  Это коллекция, а не один нативный ComparisonReport.
- `results.csv`: итоговые метрики, время, трафик, число кластеров и доля шума.
- `history/*/report.json`, `results.csv`, `execution.log`: нативная история
  23 сравнений, которую читает HistoryQueryService приложения.
- `predictions/*-labels.npz`: окончательные метки для каждого объекта и прогона.
- `logs/`: исходные логи worker-процессов.
- `partitions.json`: точные индексы объектов каждого клиента, классовый состав
  и измеренная неоднородность всех шести разбиений.
- `protocol.json`, `experiment_plan.json`: параметры и полный план серии.

Чтобы открыть историю в PyClustEval, скопируйте содержимое `history/` выбранной
серии в папку `history/` своего проекта и обновите историю/перезапустите UI.
Для всех девяти серий можно объединить их history-папки. Если имена каталогов
совпали, переименуйте переносимый каталог с добавлением имени серии; загрузчик
принимает такие имена. Идентификаторы экспериментов включают имя серии и сценарий.

Для подключения всех девяти историй сразу можно выполнить из распакованного архива:

```bash
python merge_history.py --into /path/to/PyClustEval/history
```

Скрипт добавляет имя серии к именам каталогов и не перезаписывает существующие
файлы. Предсказания и исходные данные остаются в папках архива.

Программное чтение без переноса:

```python
from clustering_eval.application import HistoryQueryService
history = HistoryQueryService("mnist1/history")
for item in history.list_experiments():
    details = history.get_experiment(item.history_key)
    print(details.experiment_id, details.seed, len(details.results))
```

## Протокол

Сохранён протокол предыдущего сравнения: 10 клиентов, бюджет 20 раундов,
tol=1e-4, max_iter=300; IID, Dirichlet alpha=0.1/0.5/5, quantity skew,
label-limited (2 класса на клиента); доступность (participation, dropout):
(1,0), (0.8,0), (1,0.2), (0.5,0.2). Для alpha=0.5 и 5 — полная доступность.
DP: epsilon=20/10/5/1, delta=1e-5, clip=4, IID и полная доступность.
Пять авторских DP-вариантов — модифицированные прокси и явно помечены `[DP proxy]`.

Каждый датасет фиксирован для трёх повторов; меняются seed алгоритмов,
разбиения по клиентам и расписание доступности. MNIST использует прежнюю
каноническую стратифицированную выборку 10k с subset seed=42; benchmark seeds
211/307/401 не заменяют subset seed. Синтетические данные сгенерированы один
раз с generator seed=314159. DP-шум получает случайность от ОС и намеренно
не фиксируется benchmark seed. Не все авторские методы используют общий
раундовый бюджет: реальные rounds и фактические параметры сохранены.
Детерминированные методы (например, agglomerative и DBSCAN на фиксированном X)
могут давать одинаковые метрики при разных benchmark seed; это ожидаемо.

Предобработка и параметры алгоритмов сохранены прежними, без оптимизации под
датасеты и без PCA. Возможные вырожденные результаты не отбрасывались.
ARI/AMI/NMI вычислены по всем объектам. Геометрические метрики исключают noise;
silhouette использует фиксированный набор до 2 000 объектов. Неопределённые
метрики представлены JSON null. ARI — не процент точности распознавания.

## Данные

`datasets/` содержит полные фактически использованные X и y в `dataset.npz`,
проверки размеров/контрольных сумм и описание происхождения. Алгоритмам y
не передавался, кроме открыто заданного количества кластеров; классы нужны
оценщику и label-aware non-IID-разбиениям.

Dry Bean получен из публичного зеркала исходного UCI XLSX, поскольку UCI
недоступен из среды; проверены 13 611 строк, 16 признаков и точные размеры
семи классов. Зеркало, commit, SHA256 и преобразование XLSX → ARFF указаны
в `reproduce/drybean_source.json` и dataset verification.

Синтетика — восемь пересекающихся многомерных Gaussian-популяций разного
размера, с разными ориентациями и ковариациями (condition number=20),
12 информативными и 12 шумовыми измерениями, общей случайной ротацией.
Параметры генератора фиксированы до измерений. Для aggregate DP используются
теоретические моменты публичного генератора, а не fitted scaler по выборке.
Это не три далеко разнесённых шарообразных облака. Контроль сложности
сохранён отдельно в `datasets/synthetic_anisotropic/difficulty_check.json`.

## Исполнение и проверка

Flower-строки выполнены настоящими Flower/Ray. Две вычислительные дорожки
работают на непересекающихся наборах по два CPU; BLAS threads=2. Ray runtime
и stateless worker actors переиспользуются. ClientApp, сервер, модель и Context
создаются заново для каждого запуска; client_fn создаёт NumPyClient при
обработке каждого сообщения.
На границах запусков проверяется отсутствие незавершённых задач. Фабрика
ClientApp сохраняется в Ray object store один раз на симуляцию, чтобы не
сериализовать весь MNIST в каждом сообщении. Алгоритмические вычисления
не изменены; эквивалентность проверена на исходных cold-start результатах.

`runtime_sec` измеряет алгоритм/симуляцию на инициализированной инфраструктуре;
первичная инициализация Flower записана отдельно. Время может зависеть от
совместного использования памяти/ресурсов хоста; оно не является строгим
сравнением с предыдущей средой. Трафик — logical payload, а не сетевые пакеты.
Отметки начала/конца каждого worker записаны непосредственно в UTC. Даты
нативной истории показаны по Москве (Europe/Moscow) в совместимом с UI формате;
точные UTC-значения сохранены в source_run. Длительность сравнения — интервал
между его отдельными workers. Истории раундов сохранены
без выдуманных точек: если адаптер не возвращал историю, список остаётся пустым.

`all_results.csv` объединяет 1 620 строк. `aggregate_by_dataset.csv` даёт
mean/std/min/max по трём сидам для каждого алгоритма и сценария; std — выборочное
(ddof=1), число определённых значений указано отдельно. Это описательная
статистика трёх повторов, не доказательство статистической значимости.

`reproduce/` содержит использованный исходный код, скрипты и версии пакетов.
Скрипты сохраняют пути исходной облачной среды `/workspace`; для запуска в
другом расположении пути следует заменить. `checksums.json` перечисляет SHA256
файлов, `verification.json` — результаты проверки нативной истории, метрик,
историй раундов, предсказаний и полноты разбиений. Word-файлов в архиве нет.
'''

if __name__=='__main__':main()
