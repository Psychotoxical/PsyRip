#!/bin/sh
# Startet psyrip unter Linux aus dem Quellcode (legt beim ersten Start .venv an und installiert die Abhängigkeiten).
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt || exit 1
fi
exec .venv/bin/python -m psyrip "$@"
