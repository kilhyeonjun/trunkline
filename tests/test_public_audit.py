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
