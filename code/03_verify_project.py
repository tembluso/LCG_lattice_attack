"""Standalone verification runner for the final RNG project package.

This script does not import another project file. It executes the standalone
programs as subprocesses, then independently checks their generated artifacts.
"""

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = PROJECT_ROOT / "code"
RESULTS_DIR = PROJECT_ROOT / "results"


def run(command: list[str]) -> None:
    print("RUN", " ".join(command))
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def read_csv(name: str) -> list[dict]:
    with (RESULTS_DIR / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def verify_results() -> None:
    baseline = read_csv("baseline_trials.csv")
    main = read_csv("main_104_hidden_bits_trials.csv")
    raw = read_csv("attack_matrix_raw.csv")
    summary = read_csv("attack_matrix_summary.csv")

    assert len(baseline) == 1000
    assert all(row["success"] == "True" for row in baseline)
    assert len(main) == 100
    assert all(row["success"] == "True" for row in main)
    assert len(raw) == 5 * 7 * 30
    assert len(summary) == 5 * 7

    indexed = {
        (int(row["visible_bits"]), int(row["observations_used"])): int(row["successes"])
        for row in summary
    }
    expected_boundary = {
        (16, 8): 0,
        (16, 9): 30,
        (24, 5): 0,
        (24, 6): 30,
        (32, 4): 1,
        (32, 5): 30,
        (48, 3): 30,
        (64, 3): 30,
    }
    for key, expected in expected_boundary.items():
        assert indexed[key] == expected, (key, indexed[key], expected)

    transcript = (RESULTS_DIR / "demo_transcript.txt").read_text(encoding="utf-8")
    assert "Attack successful:                         True" in transcript

    environment = json.loads((RESULTS_DIR / "environment.json").read_text(encoding="utf-8"))
    assert environment["state_bits"] == 128
    assert environment["main_hidden_bits"] == 104
    assert environment["dependencies"] == "Python standard library only"

    manifest = json.loads((RESULTS_DIR / "manifest.json").read_text(encoding="utf-8"))
    for name, expected_hash in manifest["sha256"].items():
        actual_hash = hashlib.sha256((RESULTS_DIR / name).read_bytes()).hexdigest()
        assert actual_hash == expected_hash, name

    print("All result files and boundary checks passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--full",
        action="store_true",
        help="regenerate all results before verifying them",
    )
    args = parser.parse_args()

    run([sys.executable, str(CODE_DIR / "01_complete_output_baseline.py"), "--self-test"])
    run([sys.executable, str(CODE_DIR / "02_truncated_lcg_project.py"), "self-test"])

    if args.full:
        run([sys.executable, str(CODE_DIR / "01_complete_output_baseline.py")])
        run([sys.executable, str(CODE_DIR / "02_truncated_lcg_project.py"), "all"])

    verify_results()


if __name__ == "__main__":
    main()
