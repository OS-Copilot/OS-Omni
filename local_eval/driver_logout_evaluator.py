"""Preserve final-screen checks and require evidence of the requested workflow."""
import json
from pathlib import Path
from core.evaluation import BaseEvaluator, EvalResult, EvalStatus
from evaluators.android.cua_review_state import ForegroundTextEvaluator


def workflow_events_pass(events):
    login=next((i for i,e in enumerate(events) if e['path']=='/auth/login' and e.get('body',{}).get('email')=='rider@example.com'),None)
    logout=next((i for i,e in enumerate(events) if e['path']=='/auth/logout'),None)
    ticket=next((i for i,e in enumerate(events) if e['path']=='/support/tickets' and e.get('body',{}).get('message')=='Need ride help'),None)
    return login is not None and logout is not None and ticket is not None and login < ticket < logout


class DriverLogoutWorkflowEvaluator(BaseEvaluator):
    def evaluate(self, context):
        original=ForegroundTextEvaluator().evaluate(context)
        try:
            state=json.loads(Path(__file__).with_name('opendriver-backend-state.json').read_text(encoding='utf-8'))
            evidence=workflow_events_pass(state.get('events',[]))
        except Exception as exc:
            return EvalResult(EvalStatus.ERROR,f'Cannot read reconstructed backend event evidence: {exc}',{'original_status':original.status.value,'original_metadata':original.metadata})
        metadata={'original_status':original.status.value,'original_metadata':original.metadata,'workflow_events_verified':evidence,'repair':'Final login screen is also the initial screen; require login, requested support ticket creation, and logout in sequence','read_only':True}
        if original.status==EvalStatus.ERROR:
            return EvalResult(original.status,original.message,metadata)
        passed=original.status==EvalStatus.PASS and evidence
        return EvalResult(EvalStatus.PASS if passed else EvalStatus.FAIL,'Rider workflow and final logout verified' if passed else 'Rider workflow or final logout incomplete',metadata)
