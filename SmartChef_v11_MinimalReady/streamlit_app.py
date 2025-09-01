import runpy
from pathlib import Path
APP = Path(__file__).resolve().parent / "smartchef_app" / "app.py"
runpy.run_path(str(APP))
