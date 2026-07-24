import tomllib
import subprocess
from pathlib import Path


def test_console_script_and_license_metadata():
    data = tomllib.loads(Path("pyproject.toml").read_text())
    project = data["project"]
    assert project["scripts"]["trunkline"] == "trunkline.cli:main"
    assert project["license"] == {"file": "LICENSE"}
    assert project["readme"] == "README.md"


def test_wheel_excludes_private_development_artifacts():
    data = tomllib.loads(Path("pyproject.toml").read_text())
    excluded = data["tool"]["setuptools"]["exclude-package-data"]["*"]
    assert ".superpowers/*" in excluded
    assert "telegram-plugin/*" in excluded


def test_public_project_files_exist():
    for name in [
        "LICENSE",
        "README.md",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "THIRD_PARTY_NOTICES.md",
    ]:
        assert Path(name).is_file()


def test_private_artifacts_are_absent():
    assert not Path(".superpowers/sdd").exists()
    assert not Path("docs/superpowers").exists()
    assert not Path("telegram-plugin").exists()


def test_no_personal_absolute_paths_in_release_sources():
    personal_root = "/" + "Users" + "/" + "gameduo"
    offenders = []
    tracked = subprocess.run(
        ["git", "ls-files", "trunkline", "menubar", "scripts", "tests"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.splitlines()
    for name in tracked:
        path = Path(name)
        if path.is_file() and path.suffix not in {".icns", ".png"}:
            text = path.read_text(errors="ignore")
            if personal_root in text:
                offenders.append(name)
    assert offenders == []
