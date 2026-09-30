"""pytest entry for the Synapse Cut playbook checks (tests/playbook_checks.py).

The checks run in their own process: they import main.py (models), patch
module functions and toggle SYNAPSE_PLAYBOOK, none of which may leak into the
other tests of the session."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_playbook_checks():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "playbook_checks.py")],
                       cwd=ROOT, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout[-2000:] + "\n" + r.stderr[-4000:]
    assert "test_playbook OK" in r.stdout
