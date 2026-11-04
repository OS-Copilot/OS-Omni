import json

from initializers.windows.opentwitter import OpenTwitterInitializer


class Controller:
    def __init__(self, listeners=None):
        self.listeners = listeners or []
        self.launched = []

    def run_powershell_script(self, script, **kwargs):
        assert 'Stop-Process' in script
        return {'returncode': 0}

    def run_python_script(self, script, **kwargs):
        data = {'listeners': self.listeners}
        if '/api/evaluation' in script:
            data = {'listeners': [{'name': 'opentwitter.exe', 'pid': 123}],
                    'session': {'loggedIn': False, 'user': None}, 'event_count': 0}
        return {'returncode': 0, 'output': json.dumps(data)}

    def launch_app(self, app):
        self.launched.append(app)


def test_unrelated_port_owner_blocks_launch():
    controller = Controller([{'name': 'other.exe', 'pid': 456}])
    result = OpenTwitterInitializer().initialize({'controller': controller})
    assert result.status.value == 'ERROR'
    assert 'occupied' in result.message
    assert not controller.launched


def test_clean_port_and_signed_out_backend_pass(monkeypatch):
    monkeypatch.setattr('initializers.windows.opentwitter.focus_electron_window', lambda *a: {'foreground_confirmed': True})
    controller = Controller()
    result = OpenTwitterInitializer().initialize({'controller': controller})
    assert result.status.value == 'PASS'
    assert result.metadata['port'] == 4350
    assert controller.launched == ['OpenTwitter']


def test_probe_failure_is_error_not_success():
    controller = Controller()
    controller.run_python_script = lambda *a, **kw: {'returncode': 1}
    result = OpenTwitterInitializer().initialize({'controller': controller})
    assert result.status.value == 'ERROR'
    assert not controller.launched
