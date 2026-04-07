#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
echo "開啟瀏覽器：http://127.0.0.1:5566"
open http://127.0.0.1:5566
python app.py
