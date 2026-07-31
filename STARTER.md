deactivate
Remove-Item -Recurse -Force .venv

py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -e ".[flower]"
python -m pip install "flwr[simulation]"
python -m pip install -e ".[dev]"

python pyclusteval_ui_fixed_local.py