#!/bin/sh
# Runs the Python tests with the original author's entity mapping as fixture.
cd "$(dirname "$0")"
export HAUSAKKU_SETTINGS="$PWD/tests/fixtures/settings_legacy.json"
export HAUSAKKU_MODE=publish
export HAUSAKKU_DATA="${TMPDIR:-/tmp}/hausakku-test-data"
PYTHONPATH=../app ${PYTHON:-python3} -m unittest discover -s tests -p 'test_*.py' "$@"
