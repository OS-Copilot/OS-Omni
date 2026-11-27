"""Restore missing source search anchor; leave all required agent outputs absent."""
import hashlib
import time
import json
import shlex
from pathlib import Path
from core.init import BaseInitializer, InitResult, InitStatus, load_initializer
from evaluators.cua_review.platforms.android.deltachat_store import DeltaChatAndroidStore

ROOT=Path(__file__).resolve().parents[1]

MEDIA = {
 'bot_evidence': ['phone_repair','rain_street'],
 'delivery_claim': ['delivery_livingroom'],
 'mobility_safety': ['riverside_bike','coffee_pastry','dashboard_warning'],
 'release_control': ['office_desk','meeting_room','receiving_boxes','phone_repair'],
 'river_park': ['park_event','grocery_bag','restaurant_meal'],
}

def seed_media(controller,task_id):
    names=next((v for k,v in MEDIA.items() if k in task_id),None)
    if not names: raise RuntimeError('Missing source media mapping')
    manifest=json.loads((ROOT/'local_eval/delta-media/manifest.json').read_text(encoding='utf-8'))
    records=[]
    controller.execute_adb(['shell','mkdir','-p','/sdcard/Pictures/OSOmniInputs'])
    for index,name in enumerate(names,1):
        source=ROOT/'local_eval/delta-media'/ (name+'.png')
        digest=manifest['assets'][name]['sha256']
        if hashlib.sha256(source.read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Source media checksum mismatch: '+name)
        remote=f'/sdcard/Pictures/OSOmniInputs/source_{index:02d}.png'
        controller.execute_adb(['push',str(source),remote])
        actual=controller.execute_adb(['shell','sha256sum',remote]).split()[0]
        if actual!=digest: raise RuntimeError('Device media checksum mismatch')
        controller.execute_adb(['shell','am','broadcast','-a','android.intent.action.MEDIA_SCANNER_SCAN_FILE','-d','file://'+remote])
        records.append({'scene':name,'path':remote,'sha256':digest})
    for attempt in range(15):
        indexed=controller.execute_adb(['shell','content','query','--uri','content://media/external/images/media','--projection','_id:_display_name:_data'])
        if all(r['path'].replace('/sdcard/','/storage/emulated/0/') in indexed for r in records): break
        time.sleep(1)
    else: raise RuntimeError('Required photo missing from Android MediaStore')
    return {'provenance':manifest['provenance'],'media_index_verified':True,'photos':records}

class RecoveredDeltaInitializer(BaseInitializer):
    def initialize(self,context):
        params=dict(context.get('params') or {})
        source=params.pop('source_initializer')
        controller=context['controller'];task_id=context['task'].id
        provenance={'original_initializer':source,'source_input_repair':False}
        try:
            provenance['reconstructed_media']=seed_media(controller,task_id)
            provenance['source_input_repair']=True
            if 'river_park_action_team' in task_id:
                controller.execute_adb(['shell','am','force-stop','chat.delta'])
                remote=DeltaChatAndroidStore(controller).database_path()
                if not remote.startswith('/data/data/chat.delta/files/accounts/') or not remote.endswith('/dc.db'):
                    raise RuntimeError('Unexpected benchmark account database path')
                owner=controller.execute_adb(['shell','stat','-c','%u',remote]).strip()
                if not owner.isdigit():
                    raise RuntimeError('Cannot determine app database owner')
                controller.execute_adb(['shell','rm','-f',remote+'-wal',remote+'-shm'])
                fixture=ROOT/'local_eval/deltachat-river-input.db'
                controller.execute_adb(['push',str(fixture),remote])
                controller.execute_adb(['shell','chown',owner+':'+owner,remote])
                controller.execute_adb(['shell','chmod','600',remote])
                store=DeltaChatAndroidStore(controller)
                messages=store.read_chat_messages()
                if not any('android_zoe_unread_11' in msg.get('text','') for msg in messages):
                    raise RuntimeError('Reconstructed source marker is not readable on device')
                if any(chat.get('name')=='River Park Action Team' for chat in store.read_chats()):
                    raise RuntimeError('Reconstructed baseline contains the requested final group')
                provenance.update(source_input_repair=True,added_source_token='android_zoe_unread_11',source_payload='Unread Zoe expansion 11; timestamp immediately before existing final headline message',original_headline_preserved=True)
            result=load_initializer(source).initialize(dict(context,params=params))
            if result.status != InitStatus.PASS:
                return result
            if 'delivery_claim_record' in task_id:
                controller.execute_adb(['shell','monkey','-p','net.gsantner.markor','-c','android.intent.category.LAUNCHER','1'])
                provenance['initial_foreground_repair']='Markor; instruction begins with its red new-note button'
            Path(context['run_dir'],'deltachat-input-provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
            return InitResult(InitStatus.PASS,'Verified/reconstructed DeltaChat source inputs and starting foreground',provenance)
        except Exception as exc:
            return InitResult(InitStatus.ERROR,f'DeltaChat source reconstruction failed: {exc}',provenance)
