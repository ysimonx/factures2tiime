rm -Rf ./venv
python3.14 -m venv ./venv
source ./venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
rm .env
ln -s /Users/ysimonx/Documents/secrets/factures2time/env ./.env
python scripts/setup_gmail.py --account gmail_perso
python scripts/setup_gmail.py
python scripts/run_now.py
