#!/usr/bin/env python3
"""Real iOS preflight on a disposable audit simulator; never a formal device.

No model client is instantiated. Output is a new directory containing
preflight.json, screenshot and observation. Only initializer PASS, an existing
screenshot, valid coordinate dimensions and initial evaluator FAIL qualify.
"""
import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path = [str(ROOT)] + [p for p in sys.path if p != str(ROOT)]


def find_task_file(task_id):
    import yaml
    from platforms.ios.core.types import load_task_from_file
    for path in sorted((ROOT / 'tasks/v1/ios').glob('*.yaml')):
        task = load_task_from_file(str(path))
        if task.id == task_id:
            return path, task, yaml.safe_load(path.read_text(encoding='utf-8'))
    raise ValueError(f'Unknown iOS task: {task_id}')


def run_preflight(task_id, udid, output, wda_derived_data=None):
    from PIL import Image
    from platforms.ios.runtime_env.controller import iOSController
    from platforms.ios.runners.initialization import run_task_initialization
    from platforms.ios.runners.evaluation import run_task_evaluation
    from scripts.author_eval_queue import task_implementation_hash
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)  # Never overwrite prior evidence.
    record = dict(task_id=task_id, audit_udid=udid, started=datetime.datetime.now(datetime.timezone.utc).isoformat(), preflight_status='FAIL')
    controller = None
    try:
        path, task, task_doc = find_task_file(task_id)
        record.update(task_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), task_implementation_sha256=task_implementation_hash(path))
        controller = iOSController(udid=udid, screenshot_dir=str(output), derived_data_path=wda_derived_data)
        init = run_task_initialization(task=task, controller=controller, model_id='deepseek_flash', run_dir=output)
        record['initializer'] = dict(status=init.result.status.value, message=init.result.message, metadata=init.result.metadata)
        if task_id.startswith('ios.calendar.') and task_doc.get('init', {}).get('params', {}).get('purge_all_events'):
            from platforms.ios.calendar_store import IOSCalendarStore
            native = IOSCalendarStore.from_simulator(udid)
            visible_events = native.list_events(visible_calendars_only=True)
            expected = len(task_doc.get('init', {}).get('params', {}).get('seed_events', []) or [])
            record['native_seed_state'] = {
                'expected_visible_event_count': expected,
                'observed_visible_event_count': len(visible_events),
                'observed_visible_summaries': [event.summary for event in visible_events],
            }
            if init.result.status.value != 'PASS' or len(visible_events) != expected:
                raise RuntimeError('Calendar initializer did not produce the exact visible seed state')
        observation = controller.observe(include_ui_tree=False)
        (output / 'observation.json').write_text(observation.to_json())
        screenshot = Path(controller.save_screenshot('initial'))
        if not screenshot.is_file():
            raise RuntimeError('Screenshot not saved')
        record['screenshot'] = str(screenshot)
        with Image.open(screenshot) as image:
            physical = image.size
        logical = controller.driver.get_window_size()
        if min(physical) <= 0 or min(logical['width'], logical['height']) <= 0:
            raise RuntimeError('Invalid coordinate dimensions')
        record['coordinate_dimensions'] = dict(logical=logical, physical=list(physical), scale_x=physical[0]/logical['width'], scale_y=physical[1]/logical['height'])
        evaluation = run_task_evaluation(
            task=task,
            controller=controller,
            model_id='deepseek_flash',
            run_dir=output,
            final_observation=observation,
            initialization=init.summary,
        ).result
        record['initial_evaluation'] = dict(status=evaluation.status.value, message=evaluation.message, metadata=evaluation.metadata)
        if init.result.status.value == 'PASS' and evaluation.status.value == 'FAIL' and 'error' not in record:
            record['preflight_status'] = 'PASS'
    except Exception as exc:
        record['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        if controller:
            try:
                controller.quit()
            except Exception as exc:
                record['quit_error'] = f'{type(exc).__name__}: {exc}'
                record['preflight_status'] = 'FAIL'
        record['ended'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (output / 'preflight.json').write_text(json.dumps(record, indent=2) + '\n')
    return 0 if record['preflight_status'] == 'PASS' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--udid', required=True, help='Disposable audit simulator only')
    parser.add_argument('--output', required=True, type=Path, help='New output directory')
    parser.add_argument('--wda-derived-data', default=None)
    args = parser.parse_args()
    return run_preflight(args.task_id, args.udid, args.output, args.wda_derived_data)


if __name__ == '__main__':
    raise SystemExit(main())
