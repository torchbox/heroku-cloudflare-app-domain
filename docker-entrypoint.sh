#!/usr/bin/env sh

set -e

if [ -n "$INTERVAL" ]
then
    python3 /app/main.py
else
    webhook -hooks /app/hooks.yaml -template -verbose
fi
