"""Prepare the recovered backend and wait for the native Flutter login UI."""
import time, json
import urllib.request
from core.init import BaseInitializer, InitResult, InitStatus, load_initializer

class RecoveredDriverInitializer(BaseInitializer):
    def initialize(self, context):
        params=dict(context.get('params') or {})
        source=params.pop('source_initializer')
        try:
            scenario='rider_full_service' if 'rider_full_service_logout' in context['task'].id else 'empty_workflow'
            if 'driver_workspace_support_ticket' in context['task'].id:
                scenario='driver_workspace_support'
            request=urllib.request.Request('http://127.0.0.1:4321/dev/scenario',data=json.dumps({'scenario':scenario}).encode(),headers={'Content-Type':'application/json'},method='POST')
            with urllib.request.urlopen(request,timeout=5) as response:
                if response.status!=200:
                    raise RuntimeError('Backend reset failed')
            result=load_initializer(source).initialize(dict(context,params=params))
            if result.status != InitStatus.PASS:
                return result
            if 'three_scheduled_bay_rides' in context['task'].id:
                # Restore the task's business calendar on the emulator only.
                # Otherwise the current host date makes August 30/31 unselectable.
                controller=context['controller']
                controller.execute_adb(['shell','settings','put','global','auto_time','0'])
                controller.execute_adb(['shell',"su 0 date -s '2026-08-29 00:00:00'"])
            time.sleep(20)
            return InitResult(InitStatus.PASS,'Reconstructed OpenDriver API baseline; native Flutter startup allowed to settle',{'replacement_backend':True,'original_initializer':source})
        except Exception as exc:
            return InitResult(InitStatus.ERROR,f'OpenDriver environment failed: {exc}')
