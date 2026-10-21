"""Read the installed static app; a never-written key denotes its APK initial state."""
import importlib
import json
import re
from pathlib import Path
from core.evaluation import BaseEvaluator, EvalResult
from evaluators.cua_review.platforms.android.webview_devtools import WebViewDevTools

ROOT=Path(__file__).resolve().parents[1]

def apk_initial_state():
    source=(ROOT/'local_eval/app_assets/openfood/assets/public/app.js').read_text(encoding='utf-8')
    literal=re.search(r'const initialState = (\{.*?\n  \});',source,re.S).group(1)
    document=json.loads(re.sub(r'(\b[A-Za-z]\w*)\s*:',r'"\1":',literal))
    if document['createdOrders'] or document['tickets'] or document['cart']:
        raise RuntimeError('APK initial state unexpectedly contains workflow results')
    return document

class StaticOpenFoodEvaluator(BaseEvaluator):
    def evaluate(self,context):
        params=dict(context.get('params') or {})
        module,name=params.pop('source_evaluator').split(':')
        original_class=getattr(importlib.import_module(module),name)
        evidence={'used_unwritten_key_fallback':False}
        def read(controller,package,key):
            page=WebViewDevTools(controller,package)
            key_json=json.dumps(key)
            result=json.loads(page.evaluate(f'JSON.stringify({{stored:localStorage.getItem({key_json}),appLoaded:!!window.OPENFOOD_DATA && document.body.innerText.includes("OpenFood")}})'))
            if result['stored'] is not None:
                return json.loads(result['stored'])
            if not result['appLoaded']:
                raise RuntimeError('Missing state key and OpenFood app is not loaded')
            evidence['used_unwritten_key_fallback']=True
            return apk_initial_state()
        repaired_class=type('InstalledStaticAppRules',(original_class,),{'_read_webview_local_storage':staticmethod(read)})
        result=repaired_class().evaluate(dict(context,params=params))
        metadata=dict(result.metadata)
        metadata['compatibility_repair']={**evidence,'reason':'Installed app writes localStorage only after an action; absent key uses verified APK initialState','source_evaluator':module+':'+name,'business_rules_changed':False}
        return EvalResult(result.status,result.message,metadata)
