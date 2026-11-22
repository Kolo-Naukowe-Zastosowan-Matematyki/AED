#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
docker run --rm -v "$(pwd):/work:ro" -w /work -e PYTHONDONTWRITEBYTECODE=1 python:3.8.20-bullseye sh -ec 'pip -q install Django==2.2.9 openpyxl==3.1.5 && python -m unittest discover -s tests'

