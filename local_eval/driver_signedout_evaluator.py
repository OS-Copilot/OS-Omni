"""Treat a verified signed-out native client as an unmet task, preserving errors."""
import importlib
from evaluators.cua_review.core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.cua_review.platforms.android.opendriver_support import read_accessibility_text, read_foreground_window

class NativeDriverScheduledEvaluator(BaseEvaluator):
    def evaluate(self, context):
        params = dict(context.get('params') or {})
        source = params.pop('source_evaluator')
        module, name = source.split(':')
        original = getattr(importlib.import_module(module), name)().evaluate(dict(context, params=params))
        if original.status != EvalStatus.ERROR or 'storage carries no service credential' not in original.message:
            return original
        controller = context['controller']
        text = read_accessibility_text(controller).casefold()
        window = read_foreground_window(controller)
        signed_out = 'sign in' in text and 'choose a workspace' in text and 'rider' in text and 'driver' in text
        if 'com.killt.opendriver' in window and signed_out:
            return EvalResult(EvalStatus.FAIL, 'OpenDriver is signed out; scheduled rides require the requested signed-in account', {
                'checks': {'required_signed_in_account': False},
                'original_status': original.status.value, 'original_message': original.message,
                'original_metadata': original.metadata, 'read_only': True,
                'compatibility_repair': {'original_status': original.status.value, 'reason': 'Native login screen without a credential is an unmet task, not a state-read error'},
            })
        return original
