import importlib.util
import io
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("terminal_brand", Path(__file__).resolve().parents[1] / 'earthglass' / "terminal_brand.py")
brand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brand)

class Terminal(io.StringIO):
    def isatty(self):
        return True

def test_redirected_streams_are_clean():
    out, err = io.StringIO(), io.StringIO()
    with patch.object(brand.sys, 'stdout', out), patch.object(brand.sys, 'stderr', err):
        brand.show_banner()
    assert out.getvalue() == err.getvalue() == ''

def test_piped_stdout_suppresses_banner():
    out, err = io.StringIO(), Terminal()
    with patch.object(brand.sys, 'stdout', out), patch.object(brand.sys, 'stderr', err):
        brand.show_banner()
    assert out.getvalue() == err.getvalue() == ''

def test_explicit_banner_is_stderr_only():
    out, err = io.StringIO(), io.StringIO()
    with patch.object(brand.sys, 'stdout', out), patch.object(brand.sys, 'stderr', err):
        brand.show_banner(force=True)
    assert out.getvalue() == ''
    assert brand.PRODUCT in err.getvalue()
    assert 'BLACKFONG / PROJECTS' in err.getvalue()
    assert '\x1b' not in err.getvalue()

def test_no_color_and_dumb_terminal():
    for env in ({'NO_COLOR': ''}, {'TERM': 'dumb'}):
        out, err = Terminal(), Terminal()
        with patch.object(brand.sys, 'stdout', out), patch.object(brand.sys, 'stderr', err), patch.dict(brand.os.environ, env, clear=True):
            brand.show_banner()
        assert brand.PRODUCT in err.getvalue()
        assert '\x1b' not in err.getvalue()

def test_version_uses_metadata_with_source_fallback():
    with patch.object(brand, 'version', return_value='9.8.7'):
        assert brand.product_version() == '9.8.7'
    with patch.object(brand, 'version', side_effect=brand.PackageNotFoundError):
        assert brand.product_version() == brand.SOURCE_VERSION
