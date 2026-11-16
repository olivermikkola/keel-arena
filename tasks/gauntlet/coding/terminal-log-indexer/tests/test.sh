#!/bin/sh
set -eu
chmod 700 /tests /logs/verifier
python3 -I -S /tests/judge.py
