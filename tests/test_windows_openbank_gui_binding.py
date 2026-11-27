from types import SimpleNamespace

from initializers.windows import openbank_rebuilt


class Controller:
    def __init__(self, gui_ready=True):
        self.gui_ready = gui_ready
        self.launched = False
    def run_powershell_script(self, script, **kwargs):
        if 'Start-Process' in script:
            self.launched = True
        if 'webSocketDebuggerUrl' in script:
            return {'returncode': 0 if self.gui_ready else 1,
                    'output': 'OPENBANK_GUI_AUTHENTICATED' if self.gui_ready else ''}
        return {'returncode': 0, 'output': 'STOPPED'}
    def run_python_script(self, code, **kwargs):
        return {'returncode': 0, 'output': 'SEED_CUSTOMER_READY'}
    def observe(self, **kwargs):
        return SimpleNamespace(foreground_app='openbank.exe')


def bind_probe(monkeypatch, busy=False):
    monkeypatch.setattr(openbank_rebuilt, 'focus_electron_window', lambda *a: {})
    def probe(controller, port, ready):
        return {'listeners': [{'name': 'openbank.exe' if ready else 'other.exe', 'pid': 1}] if ready or busy else []}
    monkeypatch.setattr(openbank_rebuilt, 'probe_electron_backend', probe)


def test_api_login_without_authenticated_gui_is_not_accepted(monkeypatch):
    bind_probe(monkeypatch)
    result = openbank_rebuilt.OpenBankRebuiltInitializer().initialize({'controller': Controller(gui_ready=False)})
    assert result.status.value == 'ERROR'
    assert result.metadata['stage'] == 'navigate_authenticated_page'


def test_occupied_backend_port_blocks_initialization(monkeypatch):
    bind_probe(monkeypatch, busy=True)
    controller = Controller()
    result = openbank_rebuilt.OpenBankRebuiltInitializer().initialize({'controller': controller})
    assert result.status.value == 'ERROR'
    assert not controller.launched


def test_gui_and_backend_must_both_be_ready(monkeypatch):
    bind_probe(monkeypatch)
    result = openbank_rebuilt.OpenBankRebuiltInitializer().initialize({'controller': Controller()})
    assert result.status.value == 'PASS'
    assert result.metadata['gui_authenticated']
    assert result.metadata['business_goal_actions'] is False
