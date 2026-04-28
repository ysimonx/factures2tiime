rm -Rf ./venv 
python3.14 -m venv ./venv
source ./venv/bin/activate
pip install -r requirements.txt
playwright install chromium
rm .env
ln -s ~/Documents/secrets/factures2time/env .env
python scripts/run_now.py