from copy import deepcopy
import json
from pathlib import Path
import struct

import pytest
import yaml

from evaluators.cua_review.evaluators.windows.opendriver import OpenDriverAccountEvaluator
from evaluators.windows.rebuilt_driver_logout import owned_messages
from evaluators.windows.openbank_events import find_dispute_route
from evaluators.windows.openbank_task03_702660 import OpenBankTask03702660Evaluator, RULESET_SPEC

ROOT = Path(__file__).resolve().parents[1]


def test_support_tickets_and_replies_preserve_ownership():
    store = {'data': {'supportTickets': [
        {'id': 'a', 'userId': 'me', 'message': 'first',
         'replies': [{'ticketId': 'a', 'userId': 'me', 'message': 'second'}]},
        {'id': 'b', 'userId': 'other', 'message': 'foreign'}],
        'notifications': [{'id': 'n', 'userId': 'me', 'message': 'not support'}]}}
    assert OpenDriverAccountEvaluator.support_messages(store) == ['first', 'second', 'foreign']
    assert owned_messages(store, [{'id': 'me'}]) == ['first', 'second']


def test_openfood_seed_mapping_preserves_actual_mutable_state(tmp_path, monkeypatch, capsys):
    seed = {'restaurants': [{'id': 'r1', 'name': 'Restaurant'}],
            'menu': [{'id': 'm1', 'restaurantId': 'r1', 'name': 'Dish'}],
            'users': [{'id': 'u', 'name': 'Customer'}],
            'courierTasks': [{'id': 'D-346', 'restaurantId': 'r1'}]}
    payload = json.dumps(seed).encode()
    header = {'files': {'shared': {'files': {'seed-data.json': {'offset': '0', 'size': len(payload)}}}}}
    encoded = json.dumps(header).encode()
    archive = tmp_path / 'app.asar'
    archive.write_bytes(struct.pack('<IIII', 4, 8 + len(encoded), 0, len(encoded)) + encoded + payload)
    storage = tmp_path / 'storage'
    storage.mkdir()
    original = {'view': 'admin', 'createdOrders': [], 'cart': [{'itemId': 'm1', 'qty': 2}]}
    (storage / '000003.log').write_text(json.dumps(original, separators=(',', ':')))
    script = (ROOT / 'evaluators/windows/checks/openfood_local_state.ps1').read_text()
    code = script.split("$python = @'", 1)[1].split("'@", 1)[0]
    code = code.replace(r'C:\OS-Omni\Apps\OpenFood\resources\app.asar', str(archive))
    monkeypatch.setenv('OPENFOOD_LIVE_STATE', json.dumps(original))
    exec(code, {})
    report = json.loads(capsys.readouterr().out)
    assert report['menu_id_by_name'] == {'r1|Dish': 'm1'}
    assert report['courier_route_seeds'] == seed['courierTasks']
    assert report['state']['createdOrders'] == []
    assert report['state']['cart'] == original['cart']


def dispute_events():
    target = {'id': 'd', 'transactionId': 'txn'}
    expected = {'query': 'Shop', 'reason': 'Duplicate charge'}
    events = [{'seq': 1, 'type': 'transactions_viewed', 'q': 'Shop', 'total': 1},
              {'seq': 2, 'type': 'transaction_details_viewed', 'transactionId': 'txn'},
              {'seq': 3, 'type': 'transaction_dispute_submitted', 'transactionId': 'txn',
               'disputeId': 'd', 'reason': 'Duplicate charge'}]
    return target, expected, events


def test_later_inspection_does_not_erase_completed_dispute():
    target, expected, events = dispute_events()
    events.append({'seq': 20, 'type': 'transactions_viewed', 'q': 'Shop', 'total': 1})
    assert [r['seq'] for r in find_dispute_route(events, target, expected)] == [1, 2, 3]


@pytest.mark.parametrize('missing', [0, 1, 2])
def test_missing_dispute_route_step_still_fails(missing):
    target, expected, events = dispute_events()
    events.pop(missing)
    assert find_dispute_route(events, target, expected) == (None, None, None)


def bank_state():
    spec = deepcopy(RULESET_SPEC)
    state = {'events': [{'seq': 1, 'type': 'session_login_success'}], 'disputes': [],
             'billPayments': [], 'recipients': [], 'transfers': []}
    def event(kind, **values):
        state['events'].append({'seq': len(state['events']) + 1, 'type': kind, **values})
    for i, want in enumerate(spec['disputes']):
        dispute = {k: v for k, v in want.items() if k != 'query'}
        dispute.update(id=f'd{i}', transactionId=f'txn{i}', contactedMerchant=True, status='Submitted')
        state['disputes'].append(dispute)
        event('transactions_viewed', q=want['query'], total=1)
        event('transaction_details_viewed', transactionId=dispute['transactionId'])
        event('transaction_dispute_submitted', disputeId=dispute['id'],
              transactionId=dispute['transactionId'], reason=want['reason'])
    for i, want in enumerate(spec['bill_payments']):
        payment = {**want, 'id': f'pay{i}', 'status': 'Scheduled'}
        state['billPayments'].append(payment)
        event('bill_payment_scheduled', paymentId=payment['id'], **want)
    recipient = {**spec['recipient'], 'id': 'rec-test'}
    state['recipients'].append(recipient)
    event('transfer_recipient_added', recipientId=recipient['id'],
          recipientName=recipient['name'], bank=recipient['bank'], mask=recipient['mask'])
    transfer = {**spec['transfer'], 'id': 'transfer-new-runtime-id', 'recipientId': recipient['id']}
    state['transfers'].append(transfer)
    event('transfer_scheduled', transferId=transfer['id'], recipientId=recipient['id'],
          fromAccountId=transfer['fromAccountId'], amount=transfer['amount'],
          scheduledDate=transfer['scheduledDate'], memo=transfer['memo'])
    return state


def test_generated_transfer_identity_is_bound_to_correct_business_event():
    result = OpenBankTask03702660Evaluator.evaluate_state(bank_state())
    assert result.status.value == 'PASS', result.message


@pytest.mark.parametrize('mutation', ['amount', 'event_id', 'duplicate'])
def test_wrong_transfer_or_duplicate_does_not_pass(mutation):
    state = bank_state()
    if mutation == 'amount':
        state['transfers'][0]['amount'] += 1
    elif mutation == 'event_id':
        state['events'][-1]['transferId'] = 'another-transfer'
    else:
        state['transfers'].append(deepcopy(state['transfers'][0]))
    assert OpenBankTask03702660Evaluator.evaluate_state(state).status.value == 'FAIL'


@pytest.mark.parametrize('stem', [
    'openfood_place_order_from_existing_restaurants',
    'openshop_baby_care_order_574732',
    'opennote_community_meal_three_notes_1788409691786_981937',
    'opennote_live_music_visuals_three_notes_1788411372670_327795',
    'opennote_forum_arrival_three_notes_1788412586968_101704',
    'opennote_stage_makeup_three_notes_1788408391290_206403',
])
def test_task_preserves_original_workflow_instead_of_lossy_summary(stem):
    task = yaml.safe_load((ROOT / 'tasks/v1/windows' / f'{stem}.yaml').read_text(encoding='utf8'))
    source = task['metadata']['cua_tasks_review']['source_instruction'].strip()
    assert task['instruction'].endswith(source)


@pytest.mark.parametrize('stem', ['budget_add_transactions', 'budget_full_setup'])
def test_actual_transfer_links_are_counterpart_ids_not_shared_group_ids(stem):
    script = (ROOT / 'evaluators/windows/checks' / f'{stem}.ps1').read_text()
    code = script.split("$script = @'", 1)[1].split("'@", 1)[0]
    setup = code[:code.index('\nfailures=[]\nfor source')]
    namespace = {}
    exec(setup, namespace)
    rows = [{'id': 'out', 'transfer_id': 'in', 'account_name': 'Ops Checking', 'amount': -30000},
            {'id': 'in', 'transfer_id': 'out', 'account_name': 'Travel Envelope', 'amount': 30000}]
    match = namespace['has_transfer']
    assert match(rows, 'Ops Checking', 'Travel Envelope', 300)
    assert not match(rows, 'Travel Envelope', 'Ops Checking', 300)
    assert not match(rows, 'Ops Checking', 'Travel Envelope', 450)
    broken = deepcopy(rows)
    broken[1]['transfer_id'] = 'unrelated'
    assert not match(broken, 'Ops Checking', 'Travel Envelope', 300)
    # The raw transactions table exposes transferred_id; the view aliases it.
    raw = [{**{k: v for k, v in row.items() if k != 'transfer_id'},
            'transferred_id': row['transfer_id']} for row in rows]
    assert match(raw, 'Ops Checking', 'Travel Envelope', 300)


def test_food_grader_fetches_tree_when_agent_used_screenshot_only():
    from types import SimpleNamespace
    from evaluators.windows.openfood_customer_cart_cross_role_audit import OpenFoodCustomerAuditEvaluator
    class Controller:
        observed = False
        def run_powershell_script(self, *args, **kwargs):
            return {'returncode': 0, 'output': '{"windows":[],"visible_count":0}'}
        def observe(self, **kwargs):
            assert kwargs == {'include_ui_tree': True, 'include_screenshot_data': True}
            self.observed = True
            return SimpleNamespace(ui_nodes=[{'text': 'Admin All orders OF-2001 OF-2002'}],
                                   screenshot_data=b'', foreground_app='openfood.exe', foreground_window='OpenFood')
    controller = Controller()
    final = SimpleNamespace(ui_nodes=[], screenshot_data=b'old-agent-screen')
    result = OpenFoodCustomerAuditEvaluator._read_ui_state(controller, {'process_name': 'openfood', 'window_title_contains': 'OpenFood'}, final)
    assert controller.observed
    assert 'Admin All orders OF-2001 OF-2002' in result['visible_text']


@pytest.mark.skipif(__import__('sys').platform != 'win32', reason='Windows built-in OCR integration')
@pytest.mark.parametrize('text', ['Admin All orders OF-2001 OF-2002', ''])
def test_windows_ocr_fallback_without_external_tesseract(monkeypatch, text):
    import io
    import sys
    from types import SimpleNamespace
    from PIL import Image, ImageDraw, ImageFont
    from evaluators.windows.ocr import read_screenshot_text
    def missing_tesseract(*args, **kwargs):
        raise OSError('external Tesseract deliberately unavailable')
    monkeypatch.setitem(sys.modules, 'pytesseract', SimpleNamespace(image_to_string=missing_tesseract))
    image = Image.new('RGB', (1200, 180), 'white')
    ImageDraw.Draw(image).text((20, 40), text, fill='black',
                              font=ImageFont.truetype(r'C:\Windows\Fonts\arial.ttf', 40))
    data = io.BytesIO()
    image.save(data, format='PNG')
    assert read_screenshot_text(data.getvalue()).strip() == text


@pytest.mark.parametrize('stem', [
    'openfood_place_order_from_existing_restaurants', 'openshop_baby_care_order_574732',
    'opennote_community_meal_three_notes_1788409691786_981937',
    'opennote_live_music_visuals_three_notes_1788411372670_327795',
    'opennote_forum_arrival_three_notes_1788412586968_101704',
    'opennote_stage_makeup_three_notes_1788408391290_206403',
])
def test_regeneration_preserves_original_instruction_and_evaluator(stem):
    import hashlib
    from tools.import_cua_tasks_review import _replace_instruction_with_summary
    task = yaml.safe_load((ROOT / 'tasks/v1/windows' / (stem + '.yaml')).read_text(encoding='utf8'))
    original = task['metadata']['cua_tasks_review']['source_instruction']
    evaluation = deepcopy(task['evaluation'])
    for folder in ['tasks/v1']:
        overrides = json.loads((ROOT / folder / 'cua_tasks_review_instructions.json').read_text(encoding='utf8'))
        override = overrides['instructions'][task['task_id']]
        assert override['source_instruction_sha256'] == hashlib.sha256(original.encode('utf8')).hexdigest()
        task['instruction'] = original
        _replace_instruction_with_summary(task, override)
        assert task['instruction'] == original.strip()
        assert task['metadata']['cua_tasks_review']['instruction_summary_source'] == 'preserved_source_instruction'
        assert task['evaluation'] == evaluation
