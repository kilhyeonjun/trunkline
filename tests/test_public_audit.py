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
