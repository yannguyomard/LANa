#!/bin/sh
# Lance LANa (double-clic sous macOS, ./lancer.command sous Linux). Python 3.9 ou plus récent requis.
cd "$(dirname "$0")" || exit 1
exec python3 run.py "$@"
