#!/usr/bin/env sh

set -e

if [ -z "$INTERVAL" ]
then
    python3 /app/main.py
else
    webhook -hooks /app/hooks.yaml -template -verbose
fi
