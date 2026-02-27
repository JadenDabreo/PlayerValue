import subprocess
import sys
from pathlib import Path
from datetime import datetime
import os

# Get directory of this file
BASE_DIR = Path(__file__).resolve().parent

# Scripts to run in order
SCRIPTS = [
    "contracts.py",
    "DARKO.py",
    "epm.py",
    "team_base_stats.py",
    "team_stats.py",
    "measurements.py",
    "PlayerValue.py",
    "shot_charts.py",   # slow (~8 min) — has resume support if interrupted
]

def run_script(script_name):
    script_path = BASE_DIR / script_name

    if not script_path.exists():
        print(f"[ERROR] {script_name} not found.")
        return False

    print(f"\n===== Running {script_name} =====")
    print(f"Time: {datetime.now()}\n")

    try:
        result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env={**os.environ, "PYTHONUTF8": "1"},
        )

        print(result.stdout)
        print(f"===== Finished {script_name} Successfully =====")
        return True

    except subprocess.CalledProcessError as e:
        print(f"[FAILED] {script_name}")
        print(e.stdout)
        print(e.stderr)
        return False


def main():
    print("\n=== NBA Data Pipeline Started ===")
    print(f"Start Time: {datetime.now()}\n")

    for script in SCRIPTS:
        success = run_script(script)
        if not success:
            print("\nStopping execution due to error.")
            break

    print(f"\n=== Pipeline Finished at {datetime.now()} ===\n")


if __name__ == "__main__":
    main()