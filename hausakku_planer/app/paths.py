"""Central data locations. Inside the add-on everything lives in /data."""
import os
from pathlib import Path

DATA=Path(os.environ.get('HAUSAKKU_DATA',str(Path(__file__).resolve().parent/'.data')))
STATE=DATA/'state'

def ensure():
    STATE.mkdir(parents=True,exist_ok=True)
    return STATE
