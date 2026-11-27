"""Reconstruct missing pre-task state from APK seed data, never final answers."""
import json, time
from pathlib import Path
from core.init import BaseInitializer, InitResult, InitStatus, load_initializer
from evaluators.cua_review.platforms.android.webview_devtools import WebViewDevTools

class ReconstructedBaselineInitializer(BaseInitializer):
    @staticmethod
    def wait_ready(page, expression, timeout=45):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            try:
                if page.evaluate(expression) == 'true':
                    return
            except Exception as exc:
                last = exc
            time.sleep(1)
        raise RuntimeError(f'WebView did not become ready: {last}')

    def initialize(self, context):
        params = dict(context.get('params') or {})
        original = params.pop('source_initializer')
        package = params['app_package']
        original_context = dict(context, params=params)
        result = load_initializer(original).initialize(original_context)
        if result.status != InitStatus.PASS:
            return result
        time.sleep(5)
        page = WebViewDevTools(context['controller'],package)
        app = package.removeprefix('com.killt.')
        try:
            self.wait_ready(page, "String(document.readyState === 'complete')")
            page.evaluate('JSON.stringify({ready:document.readyState,url:location.href})')
            if app == 'openfood':
                present = page.evaluate("String(localStorage.getItem('openfood-static-state-v1') !== null)") == 'true'
                baseline = {'local_state_present':present,'reconstruction':'APK bundled static initial state','observed_at':time.time()}
                Path(context['run_dir'],'openfood_baseline.json').write_text(json.dumps(baseline,indent=2),encoding='utf-8')
                if present:
                    return InitResult(InitStatus.ERROR,'OpenFood baseline contains pre-existing local state',baseline)
            elif app == 'opennavigation':
                self.wait_ready(page, "String(typeof recordsStore !== 'undefined' && document.querySelector('#records-button') !== null)")
                clean = json.loads(page.evaluate("JSON.stringify({routes:recordsStore.routes.length,incidents:recordsStore.incidents.length,signedIn:state.signedIn})"))
                Path(context['run_dir'],'opennavigation_baseline.json').write_text(json.dumps(clean,indent=2),encoding='utf-8')
                if clean['routes'] or clean['incidents']:
                    return InitResult(InitStatus.ERROR,'Navigation records must begin empty',clean)
                if not clean['signedIn']:
                    return InitResult(InitStatus.ERROR,'Navigation baseline must be signed in',clean)
            elif app == 'openbank':
                # The original tasks begin already signed in. All business records
                # remain the pristine APK seed; only the starting session changes.
                page.evaluate("""(() => {const s=JSON.parse(localStorage.getItem('openbank.localState.v7'));if(!s)throw Error('Missing seed');s.session={loggedIn:true,user:{id:s.customer.id,displayName:s.customer.displayName,preferredName:s.customer.preferredName,email:s.customer.email,phone:s.customer.phone}};s.evaluationEvents=[];s.evaluationEventSeq=0;localStorage.setItem('openbank.localState.v7',JSON.stringify(s));setTimeout(()=>location.href='./index.html',250);return 'seeded session only';})()""")
            elif app == 'opentwitter':
                handle = params.get('expected_handle','alex')
                expression = """(() => {const s=JSON.parse(localStorage.getItem('opentwitter.localState.v7'));const h=__HANDLE__;const a=s.accounts[h];if(!a)throw Error('Account not in APK seed');const u=s.users.find(x=>x.handle===h);s.session={loggedIn:true,user:{...u,email:a.email,handle:h}};s.evaluationEvents=[];s.evaluationEventSeq=0;localStorage.setItem('opentwitter.localState.v7',JSON.stringify(s));setTimeout(()=>location.href='./index.html',250);return 'seeded session only';})()""".replace('__HANDLE__',json.dumps(handle))
                page.evaluate(expression)
            elif app == 'openshop':
                self.wait_ready(page, "String(typeof readLocalState === 'function' && typeof getAccounts === 'function')")
                phone = params.get('account_phone','13800138000')
                expression = """(() => {const s=readLocalState();const a=getAccounts().find(a=>a.phone===__PHONE__);if(!a)throw Error('Account not in APK seed');s.session={loggedIn:true,user:{id:a.id,name:a.name,phone:a.phone,avatar:a.avatar}};const u=s.users[__PHONE__];const expected=__ORDERS__;const missing=expected.filter(id=>!u.orders.some(o=>o.id===id));for(const id of missing){if(id!=='TB1781113752081')throw Error('Unknown missing baseline order '+id);const source=u.orders.find(o=>o.id==='TBH-LUCAS-20260321-004');if(!source)throw Error('Missing reconstruction source');const prior=clone(source);prior.id=id;prior.createdAt='2026-06-10T16:29:12.081Z';prior.note='Reconstructed prior baseline order; original snapshot unavailable.';prior.items.forEach((item,i)=>{item.id='reconstructed-prior-'+i;delete item.review;});u.orders.unshift(prior);}writeLocalState(s);setTimeout(()=>location.href='./index.html',250);return 'seeded session only';})()""".replace('__PHONE__',json.dumps(phone)).replace('__ORDERS__',json.dumps(params.get('expected_order_ids', [])))
                page.evaluate(expression)
            elif app == 'opentrip':
                page.evaluate("""(() => {const s=JSON.parse(localStorage.getItem('opentrip.localState.v1'));const a=s.accounts.find(a=>a.name==='Lucas Lin');if(!a)throw Error('Lucas not in APK seed');s.session={loggedIn:true,user:publicUser(a)};localStorage.setItem('opentrip.localState.v1',JSON.stringify(s));setTimeout(()=>location.href='./index.html',250);return 'seeded session only';})()""")
            elif app == 'opennote':
                # Auth lives in state.session; the sessionStorage marker is not auth.
                page.evaluate("""(() => {const s=JSON.parse(localStorage.getItem('opennote.localState.v2'));if(!s)throw Error('Missing seed');s.session={loggedIn:false,user:null};s.evaluationEvents=[];s.evaluationEventSeq=0;localStorage.setItem('opennote.localState.v2',JSON.stringify(s));setTimeout(()=>location.href='./login.html',250);return 'signed out';})()""")
                self.wait_ready(page, "String(document.readyState === 'complete' && location.pathname.endsWith('/login.html'))")
                summary=json.loads(page.evaluate("JSON.stringify({url:location.href,state:JSON.parse(localStorage.getItem('opennote.localState.v2')),session:localStorage.getItem('opennote.localSession.v2')})"))
                if 'login.html' not in summary['url'] or summary.get('state',{}).get('session',{}).get('loggedIn'):
                    return InitResult(InitStatus.ERROR,'OpenNote must begin on the signed-out login page')
                targets=context.get('task')
                if summary.get('state',{}).get('evaluationEvents'):
                    return InitResult(InitStatus.ERROR,'OpenNote baseline already has evaluation events')
            time.sleep(1)
            self.wait_ready(page, "String(document.readyState === 'complete')")
            if app == 'openshop':
                state = page.read_key_as_document('openshop.localState.v3')
                user = state.get('users', {}).get(phone, {})
                ids = [o.get('id') for o in user.get('orders', [])]
                expected = params.get('expected_order_ids', [])
                if expected and ids != expected:
                    return InitResult(InitStatus.ERROR, 'OpenShop baseline order IDs do not match', {'expected': expected, 'observed': ids})
                Path(context['run_dir'], 'openshop_baseline.json').write_text(json.dumps({'order_ids': ids, 'expected_order_ids': expected, 'provenance': 'APK seed plus explicitly reconstructed prior order TB1781113752081 when required; original contents unavailable'}, indent=2), encoding='utf-8')
            if app == 'opentwitter':
                state = page.read_key_as_document('opentwitter.localState.v7')
                social = state.get('userStateByHandle', {}).get(handle, {})
                polluted = []
                targets = list(params.get('target_posts') or []) + list(params.get('additional_target_posts') or [])
                if params.get('target_post'):
                    targets.append(params['target_post'])
                for target in targets:
                    for action in target.get('actions', []):
                        key = {'like':'likedPostIds','bookmark':'bookmarkedPostIds','repost':'repostedPostIds'}.get(action)
                        if key and target.get('id') in social.get(key, []):
                            polluted.append({'post':target['id'],'action':action})
                baseline = {'evaluation_event_seq':state.get('evaluationEventSeq',0),
                            'snapshot_name':params.get('snapshot_name',''),
                            'provenance':'reconstructed APK seed; original task snapshot unavailable',
                            'polluted_target_evidence':polluted,
                            'target_follow_already_active':params.get('target_follow_handle') in social.get('followingHandles', social.get('following', [])),
                            'notification_count':len(social.get('notifications', []))}
                for filename in ('opentwitter_baseline.json','opentwitter_release_search_baseline.json'):
                    Path(context['run_dir'],filename).write_text(json.dumps(baseline,ensure_ascii=False,indent=2),encoding='utf-8')
                if polluted or baseline['target_follow_already_active']:
                    return InitResult(InitStatus.ERROR,'Twitter reconstructed seed already satisfies target actions',baseline)
            return InitResult(InitStatus.PASS,'Reconstructed and checked starting state from APK seed data',{'app_package':package,'source_initializer':original,'reconstructed':True})
        except Exception as e:
            return InitResult(InitStatus.ERROR,f'Baseline reconstruction failed: {type(e).__name__}: {e}')
