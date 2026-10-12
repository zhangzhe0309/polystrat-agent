#!/usr/bin/env bash
set -e
python3 -m unittest discover -s . -p "test_*.py"
