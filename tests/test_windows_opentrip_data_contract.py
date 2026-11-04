import pytest

from evaluators.cua_review.evaluators.windows.opentrip import OpenTripBookingEvaluator as Evaluator
from evaluators.cua_review.initializers.windows.opentrip import OpenTripInitializer
from evaluators.cua_review.initializers.windows.setup import WindowsPreparationError


def flight():
    return {
        'id': 'OT-test', 'type': 'flight', 'status': 'Confirmed',
        'item': {'id': 'f1001', 'flightNo': 'ES6821', 'from': 'SHA',
                 'to': 'SYX', 'date': '2026-06-12', 'airline': 'Eastern Star'},
        'traveler': {'id': 'traveler-maya', 'name': 'Maya Chen', 'documentType': 'Passport'},
        'payment': {'id': 'wechat', 'label': 'WeChat Pay'},
        'cabin': 'business', 'contactPhone': '13900002026', 'note': 'test',
    }


def expected():
    return {'type': 'flight', 'status': 'Confirmed', 'item_id': 'f1001',
            'flight_no': 'ES6821', 'flight_from': 'SHA', 'flight_to': 'SYX',
            'flight_date': '2026-06-12', 'traveler_id': 'traveler-maya',
            'traveler_name': 'Maya Chen', 'traveler_document_type': 'Passport',
            'contact_phone': '13900002026', 'cabin': 'business', 'note': 'test',
            'payment_id': 'wechat', 'payment_label': 'WeChat Pay', 'id_prefix': 'OT'}


def test_nested_flight_matches_without_confusing_booking_and_item_ids():
    assert Evaluator._matches(flight(), expected())
    assert Evaluator._value(flight(), 'item_id') == 'f1001'


@pytest.mark.parametrize('section,key,value', [
    ('item', 'id', 'other'), ('item', 'flightNo', 'wrong'),
    ('item', 'date', '2026-06-13'), ('item', 'to', 'CKG'),
    ('traveler', 'name', 'Other Person'), ('payment', 'id', 'card'),
])
def test_incorrect_booking_fields_still_fail(section, key, value):
    booking = flight()
    booking[section][key] = value
    assert not Evaluator._matches(booking, expected())


def test_hotel_nested_fields_are_exact():
    booking = {'id': 'OT-hotel', 'item': {'id': 'h4887', 'name': 'Chengdu Jade Pavilion Boutique Stay'},
               'room': {'id': 'suite', 'name': 'Family Suite'}, 'checkIn': '2026-06-12',
               'checkOut': '2026-06-13', 'guests': 3}
    want = {'item_id': 'h4887', 'hotel_name': 'Chengdu Jade Pavilion Boutique Stay',
            'room_id': 'suite', 'room_name': 'Family Suite',
            'check_in': '2026-06-12', 'check_out': '2026-06-13', 'guests': 3}
    assert Evaluator._matches(booking, want)
    booking['room']['id'] = 'standard'
    assert not Evaluator._matches(booking, want)


def test_duplicate_matches_still_fail(monkeypatch):
    monkeypatch.setattr(Evaluator, 'read_state', lambda *args: {'bookings': [flight(), flight()]})
    result = Evaluator().evaluate({'controller': object(), 'params': {'required_bookings': [expected()]}})
    assert result.status.value == 'FAIL'
    assert result.metadata['checks'][0]['observed']['match_count'] == 2


def test_flat_contract_still_supported():
    assert Evaluator._value({'item_id': 'legacy', 'item': {'id': 'nested'}}, 'item_id') == 'legacy'


def test_missing_seed_is_preparation_error(monkeypatch):
    from evaluators.cua_review.initializers.windows import opentrip
    monkeypatch.setattr(opentrip, 'run_python_json', lambda *a, **kw: {'missing': [{'type': 'flight', 'id': 'f2008'}]})
    with pytest.raises(WindowsPreparationError, match='seed/build'):
        OpenTripInitializer()._verify_inventory(object(), {'required_inventory': [{'type': 'flight', 'id': 'f2008'}]})


@pytest.mark.parametrize('hotel_name,missing', [
    ('Chengdu Jade Pavilion Boutique Stay', False), ('Unrelated Hotel', True),
])
def test_inventory_requires_correct_item_not_just_reused_id(tmp_path, capsys, hotel_name, missing):
    import json
    from evaluators.cua_review.initializers.windows.opentrip import INVENTORY_PROBE

    seed_path = tmp_path / 'app' / 'shared' / 'seed-data.json'
    seed_path.parent.mkdir(parents=True)
    seed_path.write_text(json.dumps({'hotels': [{'id': 'h4887', 'name': hotel_name}]}))
    required = [{'type': 'hotel', 'id': 'h4887',
                 'fields': {'name': 'Chengdu Jade Pavilion Boutique Stay'}}]
    exec(INVENTORY_PROBE, {'candidates': [str(tmp_path)], 'required': required})
    report = json.loads(capsys.readouterr().out)
    assert report['missing'] == (required if missing else [])


@pytest.mark.parametrize('date,missing', [('2026-06-01', False), ('2026-06-12', True)])
def test_inventory_rejects_reused_flight_id_with_wrong_date(tmp_path, capsys, date, missing):
    import json
    from evaluators.cua_review.initializers.windows.opentrip import INVENTORY_PROBE

    path = tmp_path / 'app' / 'shared' / 'seed-data.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'flights': [{'id': 'f2008', 'date': date}]}))
    required = [{'type': 'flight', 'id': 'f2008', 'fields': {'date': '2026-06-01'}}]
    exec(INVENTORY_PROBE, {'candidates': [str(tmp_path)], 'required': required})
    assert json.loads(capsys.readouterr().out)['missing'] == (required if missing else [])
