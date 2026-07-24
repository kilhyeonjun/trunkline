import subprocess
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
    assert "bash Scripts/package_app.sh" in workflow
    assert "python -m build --wheel" in workflow
    assert "upload-artifact" not in workflow


def test_v010_release_docs_name_exact_asset_and_limits():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text()
    notes = (root / "docs/releases/v0.1.0.md").read_text()
    asset = "trunkline-0.1.0-py3-none-any.whl"

    assert asset in readme
    assert "releases/download/v0.1.0" in readme
    assert asset in notes
    assert "macOS 14" in notes
    assert "Python 3.11" in notes
    assert "ad-hoc" in notes
    assert "notarized" in notes
    assert "SHA-256" in notes
