"""Entry point for Streamlit Cloud deployment.

Streamlit Cloud looks for streamlit_app.py at the repository root.
This delegates to the actual app in src/dashboard/app.py.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.dashboard.app import main

if __name__ == "__main__":
    main()
else:
    main()
