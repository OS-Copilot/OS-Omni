"""Fresh application observations must satisfy the unchanged order checks."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_order_initializer_loads_through_the_experiment_runner():
    from core.init import BaseInitializer, load_initializer
    initializer = load_initializer('initializers.windows.openfood_order:OpenFoodOrderInitializer')
    assert isinstance(initializer, BaseInitializer)


def states():
    rows = []
    for rid, item in [('r7', 'm61'), ('r8', 'm71'), ('r1', 'm1'), ('r2', 'm11'), ('r18', 'm171')]:
        rows.append({'view': 'restaurant', 'userId': 'lucas',
                     'selectedRestaurantId': rid, 'activeCoupon': '',
                     'cart': [{'itemId': item, 'qty': 1}], 'createdOrders': []})
    for qty in [2, 1, 2, 1]:
        snapshot = deepcopy(rows[-1])
        snapshot['cart'][0]['qty'] = qty
        rows.append(snapshot)
    rows.append({'view': 'orders', 'userId': 'lucas', 'selectedRestaurantId': 'r18',
                 'activeCoupon': '', 'cart': [], 'createdOrders': [
                     {'restaurantId': 'r18', 'userId': 'lucas', 'status': 'Preparing',
                      'items': [['m171', 1]], 'total': 15.14}]})
    return rows


@pytest.mark.parametrize('mutation', ['none', 'stale_run', 'gap', 'missing_restaurant', 'wrong_order', 'empty', 'no_adjustments', 'foreign_cart', 'malformed_item', 'wrong_owner'])
def test_trace_requires_fresh_complete_order_evidence(tmp_path, monkeypatch, capsys, mutation):
    observed = states()
    if mutation == 'missing_restaurant':
        observed.pop(1)
    if mutation == 'wrong_order':
        observed[-1]['createdOrders'][0]['restaurantId'] = 'r7'
    if mutation == 'empty':
        observed = []
    if mutation == 'no_adjustments':
        observed = observed[:5] + observed[-1:]
    if mutation == 'foreign_cart':
        for snapshot in observed[1:4]:
            snapshot['cart'] = [{'itemId': 'm61', 'qty': 1}]
    if mutation == 'malformed_item':
        observed[-1]['createdOrders'][0]['items'] = [{}]
    if mutation == 'wrong_owner':
        observed[-1]['createdOrders'][0]['userId'] = 'other'
    rows = [{'run_id': 'current', 'seq': i, 'state': state}
            for i, state in enumerate(observed, 1)]
    if mutation == 'stale_run':
        rows[0]['run_id'] = 'previous'
    if mutation == 'gap':
        rows[0]['seq'] = 2
    trace = tmp_path / 'trace.jsonl'
    trace.write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf8')
    manifest = tmp_path / 'current.json'
    manifest.write_text(json.dumps({'run_id': 'current', 'trace': str(trace)}), encoding='utf8')
    monkeypatch.setenv('OPENFOOD_TRACE_MANIFEST', str(manifest))
    seed = tmp_path / 'seed.json'
    seed.write_text(json.dumps({'menu': [
        {'id': item, 'restaurantId': rid}
        for rid, item in [('r7', 'm61'), ('r8', 'm71'), ('r1', 'm1'), ('r2', 'm11'), ('r18', 'm171')]
    ]}), encoding='utf8')
    monkeypatch.setenv('OPENFOOD_SEED_FILE', str(seed))
    task = yaml.safe_load((ROOT / 'tasks/v1/windows/openfood_place_order_from_existing_restaurants.yaml').read_text(encoding='utf8'))
    alias = yaml.safe_load((ROOT / 'tasks/windows/openfood_place_order_from_existing_restaurants.yaml').read_text(encoding='utf8'))
    assert task['evaluation'] == alias['evaluation']
    code = task['evaluation']['params']['command'].split("$code = @'", 1)[1].split("'@", 1)[0]
    exec(code, {})
    output = capsys.readouterr().out
    assert ('EVAL_RESULT:PASS' in output) == (mutation == 'none')
