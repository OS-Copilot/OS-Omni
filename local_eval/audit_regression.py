"""Offline positive/negative cases; these are never model scores."""
import sys, json, copy, importlib
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import yaml
from local_eval.openbank_evaluator import InstalledOpenBankEvaluator
from platforms.android.agent.planners.reflection_adb_planner import build_adb_action, build_adb_script_commands

checks = {}
assert build_adb_action('```adb shell input tap 10 20```')[1]
assert build_adb_action('```adb\nadb shell input tap 10 20\n```')[1]
assert not build_adb_action('```adb shell rm -rf /sdcard```')[1]
assert build_adb_script_commands('\n'.join(['adb shell input tap 1 2']*4))[1] == 'too_many_script_commands'
checks['parser_cases'] = True
for path in sorted((ROOT/'local_eval/tasks').glob('openbank*.yaml')):
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    params = data['evaluation']['params']
    module,name = params['source_evaluator'].split(':')
    cls = getattr(importlib.import_module(module),name)
    seed_path = next((ROOT/'local_eval/audit-smoke').glob('*/'+data['task_id']+'/starting-state.json'))
    seed = json.loads(json.loads(seed_path.read_text(encoding='utf-8'))['storage']['openbank.localState.v7'])
    state = copy.deepcopy(seed)
    for spec in cls.RULESET_SPEC['expected']['records'].values():
        collection = spec['collection']
        record = copy.deepcopy(spec['required'])
        if 'amount' in record:
            record['amount'] = float(record['amount'])
        if collection == 'transactions':
            record.setdefault('id','synthetic-ledger-'+str(len(state.get('transactions',[]))))
        if collection == 'disputes':
            label=record['transactionId']
            matches=[t for t in state['transactions'] if label in (t.get('merchant'),t.get('description'),t.get('note'))]
            if not matches:
                # Synthetic ledger consequence of the requested immediate transfer.
                transfer=next(x['required'] for x in cls.RULESET_SPEC['expected']['records'].values() if x['collection']=='transfers' and x['required'].get('memo')==label)
                matches=[{'id':'synthetic-transfer-ledger','merchant':transfer['recipientName'],'note':label,'date':transfer['scheduledDate']}]
                state['transactions'].extend(matches)
            record['transactionId'] = matches[0]['id']
        if collection in {'transfers','billPayments'} and record.get('scheduledDate','') > '2026-06-01':
            record['status']='Scheduled'
        lookup=spec['lookup']
        state[collection]=[r for r in state.get(collection,[]) if not all(r.get(k)==v for k,v in lookup.items())]
        state[collection].append(record)
    context={'params':params,'controller':type('Controller',(),{'execute_adb':lambda self,args:''})()}
    with patch.object(cls,'read_state',return_value=state):
        result=InstalledOpenBankEvaluator().evaluate(context)
        assert result.status.value=='PASS', (data['task_id'], result.metadata.get('failures'))
    # Removing a requested collection must never pass.
    damaged=copy.deepcopy(state)
    collection=next(iter(cls.RULESET_SPEC['expected']['records'].values()))['collection']
    damaged[collection]=[]
    with patch.object(cls,'read_state',return_value=damaged):
        assert InstalledOpenBankEvaluator().evaluate(context).status.value=='FAIL'
    checks[data['task_id']]={'positive':True,'missing_required_records_negative':True}
    if 'card_rebate' in data['task_id']:
        wrong=copy.deepcopy(state)
        next(t for t in wrong['transfers'] if t.get('memo')=='Card rebate')['scheduledDate']='2026-06-01'
        with patch.object(cls,'read_state',return_value=wrong):
            assert InstalledOpenBankEvaluator().evaluate(context).status.value=='FAIL'
        checks['calendar_wrong_date_negative']=True
        wrong=copy.deepcopy(state); wrong['disputes'][0]['details']='WRONG'
        with patch.object(cls,'read_state',return_value=wrong):
            assert InstalledOpenBankEvaluator().evaluate(context).status.value=='FAIL'
        checks['dispute_wrong_text_negative']=True
        wrong=copy.deepcopy(state);wrong['disputes'].append(copy.deepcopy(wrong['disputes'][0]))
        with patch.object(cls,'read_state',return_value=wrong):
            assert InstalledOpenBankEvaluator().evaluate(context).status.value=='FAIL'
        checks['dispute_duplicate_negative']=True
(ROOT/'local_eval/audit-regression-results.json').write_text(json.dumps({'checks':checks,'synthetic_tests_not_model_scores':True},ensure_ascii=False,indent=2),encoding='utf-8')
print('PASS:', len(checks), 'regression groups')
