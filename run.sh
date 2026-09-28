#!/usr/bin/env bash
# Full pipeline: generate messy data -> clean & load -> evaluate -> launch app
set -e
cd "$(dirname "$0")"
echo "==> 1/4 generating raw data"
python src/generate_data.py
echo "==> 2/4 cleaning + loading warehouse"
python src/build_db.py
echo "==> 3/4 running evaluation suite"
python eval/run_eval.py | tail -3
echo "==> 4/4 launching Streamlit"
streamlit run app/streamlit_app.py --server.address 0.0.0.0 --server.port 8501
