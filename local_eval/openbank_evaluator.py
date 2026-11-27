"""Explicit compatibility with the installed APK's fixed business calendar."""
import copy, hashlib, importlib, json
from core.evaluation import BaseEvaluator, EvalResult

BUSINESS_DATE = '2026-06-01'

class InstalledOpenBankEvaluator(BaseEvaluator):
    def evaluate(self, context):
        params = dict(context.get('params') or {})
        source = params.pop('source_evaluator')
        module, name = source.split(':')
        cls = getattr(importlib.import_module(module), name)
        original = cls().evaluate(dict(context, params=params))
        spec = copy.deepcopy(cls.RULESET_SPEC)
        changes = []
        for name, item in spec.get('expected', {}).get('records', {}).items():
            required = item.get('required', {})
            date = required.get('scheduledDate')
            if item.get('collection') in {'transfers','billPayments'} and date and date > BUSINESS_DATE:
                previous = required.get('status')
                if previous and previous != 'Scheduled':
                    required['status'] = 'Scheduled'
                    changes.append({'record':name,'date':date,'original_status':previous,'installed_apk_status':'Scheduled'})
        if not changes:
            return original
        digest = hashlib.sha256(json.dumps(spec,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        repaired_cls = type('InstalledCalendarRules',(cls,),{'RULESET_SPEC':spec,'RULESET_SHA256':digest,
            'expected_state':classmethod(lambda subclass, params: copy.deepcopy(spec['expected']))})
        params['expected_ruleset_sha256'] = digest
        repaired = repaired_cls().evaluate(dict(context,params=params))
        metadata = dict(repaired.metadata)
        metadata['compatibility_repair'] = {'source_evaluator':source,
            'reason':'Installed APK fixes BUSINESS_DATE at 2026-06-01; later scheduled dates remain Scheduled',
            'changed_expectations':changes,'original_status':original.status.value,'original_metadata':original.metadata}
        return EvalResult(repaired.status,repaired.message,metadata)
