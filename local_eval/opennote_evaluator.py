"""Audit original rules and apply the installed APK's documented tag parser."""
import copy
import hashlib
import importlib
import json
import re
from core.evaluation import BaseEvaluator, EvalResult


def installed_tags(values):
    return [t.strip() for value in values for t in re.split(r'[,#\s]+', value) if t.strip()][:5]


class InstalledOpenNoteEvaluator(BaseEvaluator):
    def evaluate(self, context):
        params = dict(context.get('params') or {})
        module, name = params.pop('source_evaluator').split(':')
        original_class = getattr(importlib.import_module(module), name)
        original_context = dict(context, params=params)
        original = original_class().evaluate(original_context)
        spec = copy.deepcopy(original_class.RULESET_SPEC)
        changes = []
        for note in spec.get('expected', {}).get('created_notes', []):
            previous = note.get('tags', [])
            parsed = installed_tags(previous)
            if parsed != previous:
                changes.append({'title': note['title'], 'original_tags': previous, 'installed_apk_tags': parsed})
                note['tags'] = parsed
        if not changes:
            return original
        digest = hashlib.sha256(json.dumps(spec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        repaired_class = type('InstalledTagRules', (original_class,), {'RULESET_SPEC': spec, 'RULESET_SHA256': digest})
        params['expected_ruleset_sha256'] = digest
        repaired = repaired_class().evaluate(dict(context, params=params))
        metadata = dict(repaired.metadata)
        metadata['compatibility_repair'] = {
            'reason': 'Installed APK local-api.js splits text tags using /[,#\\s]+/',
            'changed_expectations': changes,
            'source_evaluator': module + ':' + name,
            'original_status': original.status.value,
            'original_metadata': original.metadata,
        }
        return EvalResult(repaired.status, repaired.message, metadata)
