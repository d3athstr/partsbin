#!/bin/bash
cd /opt/partsbin/backend
set -a; source .env; set +a
export INGEST_LOOKBACK=2y
exec venv/bin/flask ingest run
