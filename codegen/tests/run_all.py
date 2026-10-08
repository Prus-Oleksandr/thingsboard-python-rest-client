"""Runs every codegen/tests/test_*.py against a client package and reports which ones fail.

The tests fake the HTTP layer, so no server is needed.

Usage: python3 codegen/tests/run_all.py [package_parent_dir]   (default: draft)
"""
import glob
import os
import subprocess
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
failed = []
for test in sorted(glob.glob(os.path.join(TESTS_DIR, 'test_*.py'))):
    result = subprocess.run([sys.executable, test] + sys.argv[1:], capture_output=True, text=True)
    lines = result.stdout.splitlines()
    print('%-4s %-26s %s' % ('OK' if result.returncode == 0 else 'FAIL', os.path.basename(test),
                             lines[-1] if lines else result.stderr.strip()[-200:]))
    if result.returncode != 0:
        failed.append(test)
        print('\n'.join('     ' + line for line in lines if not line.startswith('OK')))
sys.exit(1 if failed else 0)
