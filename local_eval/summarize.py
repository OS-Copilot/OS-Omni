"""Generate an auditable report from completed formal runs and queue state."""
import collections
import json
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]

def summarize():
    queue=ROOT/'local_eval/queue'
    status=json.loads((queue/'status.json').read_text(encoding='utf-8')) if (queue/'status.json').exists() else {}
    rows=[]
    counts=collections.Counter()
    for task_path in sorted((ROOT/'local_eval/tasks').glob('*.yaml')):
        task=yaml.safe_load(task_path.read_text(encoding='utf-8'))
        task_id=task['task_id'];record=status.get(task_id,{'state':'pending'})
        state=record['state'];counts[state]+=1
        result=record.get('result','—');original='—';steps=record.get('steps','—')
        failures=[]
        if record.get('report'):
            report=json.loads(Path(record['report']).read_text(encoding='utf-8'))
            metadata=(report.get('evaluation') or {}).get('metadata',{})
            repair=metadata.get('compatibility_repair',{})
            original=repair.get('original_status',metadata.get('original_status',result))
            failures=metadata.get('failures',[])
            if state == 'completed' and not record.get('excluded_from_model_score'):
                counts['result_'+result]+=1
        rows.append({'task_id':task_id,'state':state,'result':result,'original_result':original,'steps':steps,'failures':failures,'report':record.get('report'),'reconstruction':task.get('metadata',{}).get('local_repair',{})})
    document={'task_count':len(rows),'counts':dict(counts),'scope':'Reconstructed environment; original snapshot variants unavailable. Python 3.14 setup pilots excluded.','tasks':rows}
    (queue/'summary.json').write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
    done=counts['completed'];passed=counts['result_PASS'];failed=counts['result_FAIL']
    text=['# DeepSeek Flash Android 评测进度','',f'正式队列：已完成 {done}/48，PASS {passed}，FAIL {failed}；环境错误 {counts["environment_error"]}，运行器错误 {counts["runner_error"]}，执行错误 {counts["execution_error"]}。',
          '', '这是重建环境评测。缺失原始快照、替代后端、照片来源差异和判题兼容修复见 local_eval/README.md 与每题 provenance。首次 Python 3.14 环境试跑不纳入正式计数。',
          '', '| 任务 | 状态 | 修复判分 | 原始判分 | 步数 |','|---|---|---|---|---|']
    experiment_path=queue/'experiment.json'
    if experiment_path.exists() and json.loads(experiment_path.read_text(encoding='utf-8-sig')).get('benchmark_revision')=='author-rebuilt-photo-v2':
        text[4:4]=['Cooking/Guitar使用作者授权的图片v2：新生成照片、独立真实GUI参考和整图判题；其余46题保留原有效结果。旧两题报告归档，重测报告独立计分。说明见 local_eval/benchmark-v2/README.md。','']
    for row in rows:
        text.append(f'| {row["task_id"]} | {row["state"]} | {row["result"]} | {row["original_result"]} | {row["steps"]} |')
    (queue/'SUMMARY.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    return dict(counts)

if __name__=='__main__':
    print(json.dumps(summarize(),ensure_ascii=False))
