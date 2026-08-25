import os
import subprocess
import sys
from pathlib import Path


def test_reclassification_script_imports_app_without_pythonpath(tmp_path):
    repository_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [sys.executable, str(repository_root / "scripts" / "reclassify_products.py"), "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Reclassify products" in completed.stdout
