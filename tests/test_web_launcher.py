"""The launcher must explain loading before importing heavyweight AI code."""
import sys
from types import ModuleType,SimpleNamespace
import pytest
from scripts import run_web


def prepare(monkeypatch):
    monkeypatch.setenv('PORT','8018')
    monkeypatch.setenv('HOST','127.0.0.1')
    monkeypatch.setattr(run_web,'is_port_in_use',lambda port:False)
    monkeypatch.setattr(run_web.threading,'Thread',lambda **kwargs:SimpleNamespace(start=lambda:None))


def test_startup_explains_loading_before_server_import(monkeypatch,capsys):
    prepare(monkeypatch);engine=object();calls=[];output=[]
    module=ModuleType('rts_predictive.api.server')
    def load(name):
        if name=='app':
            output.append(capsys.readouterr().out)
            return engine
        raise AttributeError(name)
    module.__getattr__=load
    monkeypatch.setitem(sys.modules,'rts_predictive.api.server',module)
    monkeypatch.setattr(run_web.uvicorn,'run',lambda app,**kwargs:calls.append((app,kwargs)))
    run_web.main()
    assert 'Loading simulator and AI libraries' in ''.join(output)
    assert 'Libraries loaded. Starting web server' in capsys.readouterr().out
    assert calls==[(engine,{'host':'127.0.0.1','port':8018,'log_level':'info'})]


def test_failed_library_import_leaves_loading_progress_visible(monkeypatch,capsys):
    prepare(monkeypatch);module=ModuleType('rts_predictive.api.server')
    def load(name):
        if name=='app':raise RuntimeError('library import failed')
        raise AttributeError(name)
    module.__getattr__=load
    monkeypatch.setitem(sys.modules,'rts_predictive.api.server',module)
    with pytest.raises(RuntimeError,match='library import failed'):run_web.main()
    output=capsys.readouterr().out
    assert 'Loading simulator and AI libraries' in output
    assert 'Libraries loaded' not in output
