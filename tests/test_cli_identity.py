from typer.testing import CliRunner
from earthglass.cli import app

runner = CliRunner()

def test_help_and_version_are_branded():
    help_result = runner.invoke(app, ['--help'])
    assert help_result.exit_code == 0
    assert 'Blackfong' in help_result.output
    result = runner.invoke(app, ['--version'])
    assert result.exit_code == 0
    assert 'EarthGlass' in result.output
    assert 'BLACKFONG / PROJECTS' not in result.output


def test_unknown_command_still_fails():
    result = runner.invoke(app, ['not-a-real-command'])
    assert result.exit_code != 0
