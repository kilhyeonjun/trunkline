import re
import subprocess
import tomllib
from pathlib import Path


def test_public_audit_passes_for_release_tree():
    root = Path(__file__).parents[1]
    result = subprocess.run(
        ["bash", str(root / "scripts/audit-public-tree.sh")],
        cwd=root,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "public audit: PASS" in result.stdout


def test_ci_workflow_has_release_validation_contract():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/ci.yml").read_text()

    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert "contents: read" in workflow
    assert "actions/checkout@v7" in workflow
    assert "actions/setup-python@v7" in workflow
    assert 'python-version: ["3.11", "3.12"]' in workflow
    assert "python -m pytest -q" in workflow
    assert "bash scripts/audit-public-tree.sh" in workflow
    assert "swift test" in workflow
    assert "bash Tests/verify_release_warnings.sh" in workflow
    assert "bash Scripts/package_app.sh" in workflow
    assert "python -m build --wheel" in workflow
    assert "upload-artifact" not in workflow
    python_job = workflow.split("  python:", 1)[1].split("  public-audit:", 1)[0]
    assert "runs-on: ubuntu-latest" in python_job


def test_v010_release_docs_name_exact_asset_and_limits():
    root = Path(__file__).resolve().parents[1]
    notes = (root / "docs/releases/v0.1.0.md").read_text()
    asset = "trunkline-0.1.0-py3-none-any.whl"

    assert asset in notes
    assert "macOS 14" in notes
    assert "Python 3.11" in notes
    assert "ad-hoc" in notes
    assert "notarized" in notes
    assert "SHA-256" in notes


def test_v013_release_metadata_and_docs_stay_consistent():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    init = (root / "trunkline/__init__.py").read_text()
    readme = (root / "README.md").read_text()
    workflow = (root / ".github/workflows/ci.yml").read_text()
    notes = (root / "docs/releases/v0.1.3.md").read_text()
    asset = "trunkline-0.1.3-py3-none-any.whl"

    assert project["version"] == "0.1.3"
    assert '__version__ = "0.1.3"' in init
    assert asset in readme and "releases/download/v0.1.3" in readme
    # CI가 검사하는 wheel 이름도 계약의 일부 — 낡으면 릴리스 잡이 없는 파일을 연다
    assert f"dist/{asset}" in workflow
    assert asset in notes and "SHA-256" in notes
    assert "rollback" in notes
    # 이 릴리스가 실제로 무엇을 고쳤는지 노트가 말하도록 고정
    assert "usage HTTP 401" in notes and "cache_missing" in notes


def test_app_bundle_version_is_derived_not_hardcoded():
    """package_app.sh 가 번들 버전을 하드코딩하면 릴리스마다 낡는다 — v0.1.0부터
    v0.1.1까지 실제로 0.1.0으로 고정돼 있었고 어떤 테스트도 잡지 못했다."""
    root = Path(__file__).resolve().parents[1]
    script = (root / "menubar/Scripts/package_app.sh").read_text()
    init = (root / "trunkline/__init__.py").read_text()

    assert "<key>CFBundleShortVersionString</key><string>$VERSION</string>" in script
    assert "trunkline/__init__.py" in script
    assert not re.search(r"<string>\d+\.\d+\.\d+</string>", script)
    # 파생 실패 시 조용히 잘못된 버전을 싣지 않고 중단해야 한다
    assert 'exit 1' in script
    assert re.search(r'^__version__ = "\d+\.\d+\.\d+"$', init, re.MULTILINE)


def test_v013_rollback_instructions_are_executable_and_verified():
    root = Path(__file__).resolve().parents[1]
    notes = (root / "docs/releases/v0.1.3.md").read_text()
    url = (
        "https://github.com/kilhyeonjun/trunkline/releases/download/v0.1.2/"
        "trunkline-0.1.2-py3-none-any.whl"
    )
    checksum = "676811f7ac1521848a53c5fd89a834b66ca7bc5489aa85ea7f4472cd45de0936"

    assert f"curl -fL -o trunkline-0.1.2-py3-none-any.whl {url}" in notes
    assert f"echo '{checksum}  trunkline-0.1.2-py3-none-any.whl' | shasum -a 256 -c -" in notes
    assert "pipx install --force trunkline-0.1.2-py3-none-any.whl" in notes


def test_packaging_uses_current_spdx_license_metadata():
    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text()

    assert 'license = "MIT"' in pyproject
    assert 'license-files = ["LICENSE"]' in pyproject
    assert 'license = { file = "LICENSE" }' not in pyproject
    assert "License :: OSI Approved :: MIT License" not in pyproject
