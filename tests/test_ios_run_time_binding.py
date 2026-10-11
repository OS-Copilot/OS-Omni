import json
from datetime import datetime
from types import SimpleNamespace
from pathlib import Path
from core.init import InitResult, InitStatus
from core.evaluation import EvalResult, EvalStatus
from platforms.ios.runners import initialization, evaluation


def test_initializer_records_causal_start_before_app_actions(tmp_path, monkeypatch):
    def initialize(ctx):
        args = json.loads((tmp_path / 'args.json').read_text())
        assert datetime.fromisoformat(args['created_at']).tzinfo is not None
        assert args['task_id'] == 'ios.test'
        return InitResult(status=InitStatus.PASS, message='seeded', metadata={})
    monkeypatch.setattr(initialization, 'load_initializer', lambda _: SimpleNamespace(initialize=initialize))
    task = SimpleNamespace(id='ios.test', init=SimpleNamespace(initializer_id='test:Init', params={'return_home_after_init': False}))
    initialization.run_task_initialization(task=task, controller=object(), model_id='deepseek_flash', run_dir=tmp_path)
    before = (tmp_path / 'args.json').read_bytes()
    initialization.run_task_initialization(task=task, controller=object(), model_id='deepseek_flash', run_dir=tmp_path)
    assert (tmp_path / 'args.json').read_bytes() == before


def test_evaluator_receives_actual_episode_window_and_bound_device(tmp_path, monkeypatch):
    def evaluate(ctx):
        assert ctx['run_dir'] == tmp_path
        assert ctx['trajectory_path'] == tmp_path / 'trajectory.json'
        assert ctx['params']['udid'] == 'fresh-clone'
        assert ctx['task_id'] == 'ios.test'
        return EvalResult(status=EvalStatus.FAIL, message='unfinished', metadata={})
    monkeypatch.setattr(evaluation, 'load_evaluator', lambda _: SimpleNamespace(evaluate=evaluate))
    task = SimpleNamespace(id='ios.test', goal='task', evaluation=SimpleNamespace(evaluator_id='test:Eval', params={}))
    controller = SimpleNamespace(runtime=SimpleNamespace(udid='fresh-clone'))
    r = evaluation.run_task_evaluation(task=task, controller=controller, final_observation={}, model_id='deepseek_flash', run_dir=tmp_path, trajectory_path=tmp_path/'trajectory.json')
    assert r.result.status == EvalStatus.FAIL
