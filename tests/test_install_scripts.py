import os
import plistlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]


def run_script(name, home, *args, env=None):
    merged = os.environ | {"HOME": str(home), "TRUNKLINE_TEST_MODE": "1"}
    if env:
        merged.update(env)
    return subprocess.run(
        ["bash", str(ROOT / "scripts" / name), *args],
        text=True,
        capture_output=True,
        env=merged,
    )


def test_install_renders_resolved_cli_without_pythonpath(tmp_path):
    cli = tmp_path / "bin" / "trunkline"
    cli.parent.mkdir()
    cli.write_text("#!/bin/sh\nexit 0\n")
    cli.chmod(0o755)
    plutil = cli.parent / "plutil"
    plutil.write_text("#!/bin/sh\nexit 0\n")
    plutil.chmod(0o755)
    result = run_script(
        "install.sh",
        tmp_path,
        env={
            "PATH": f"{cli.parent}:{os.environ['PATH']}",
            "TRUNKLINE_CLI": str(cli),
        },
    )
    assert result.returncode == 0, result.stderr
    plist = plistlib.loads(
        (
            tmp_path
            / "Library/LaunchAgents/io.github.kilhyeonjun.trunkline.plist"
        ).read_bytes()
    )
    assert plist["ProgramArguments"] == [str(cli), "daemon"]
    assert "EnvironmentVariables" not in plist


def test_install_fails_without_cli(tmp_path):
    result = run_script("install.sh", tmp_path, env={"PATH": "/usr/bin:/bin"})
    assert result.returncode != 0
    assert "pipx install" in result.stderr


def test_uninstall_preserves_data_by_default(tmp_path):
    state = tmp_path / ".trunkline/state.json"
    state.parent.mkdir()
    state.write_text("{}")
    assert run_script("uninstall.sh", tmp_path).returncode == 0
    assert state.exists()


def test_uninstall_removes_data_only_when_explicit(tmp_path):
    state = tmp_path / ".trunkline/state.json"
    state.parent.mkdir()
    state.write_text("{}")
    assert run_script("uninstall.sh", tmp_path, "--remove-data").returncode == 0
    assert not state.parent.exists()
