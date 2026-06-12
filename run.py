"""
run.py
------
Quick launcher for the Streamlit app.
Usage: python run.py
"""
import os
import sys
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
APP  = os.path.join(ROOT, "app.py")

env = os.environ.copy()
env["PYTHONUTF8"] = "1"   # Fix ₹ symbol on Windows

print("=" * 60)
print("  🛒  Indian Grocery Price Comparison")
print("=" * 60)
print(f"  App   : {APP}")
print(f"  Opens : http://localhost:8501")
print("=" * 60)
print()

subprocess.run(
    [sys.executable, "-m", "streamlit", "run", APP,
     "--server.headless", "false",
     "--browser.gatherUsageStats", "false"],
    env=env,
    cwd=ROOT,
)
