"""Standalone complete-output baseline for the RNG project.

This file imports no project modules. It demonstrates the easy baseline:
three complete consecutive outputs recover the multiplier and increment of a
full-period 128-bit LCG, allowing prediction of the fourth output.
"""

import argparse
import csv
import math
import random
import statistics
import time
from pathlib import Path


STATE_BITS = 128
MODULUS = 1 << STATE_BITS
MULTIPLIER = 6_364_136_223_846_793_005
INCREMENT = 1_442_695_040_888_963_407
EXPERIMENT_SEED = 20_261_030
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = PROJECT_ROOT / "results" / "baseline_trials.csv"


def lcg_next(state: int, multiplier: int = MULTIPLIER, increment: int = INCREMENT) -> int:
    return (multiplier * state + increment) % MODULUS


def generate_states(seed: int, count: int) -> list[int]:
    states = []
    state = seed
    for _ in range(count):
        state = lcg_next(state)
        states.append(state)
    return states


def has_full_period_conditions(multiplier: int, increment: int) -> bool:
    """Hull-Dobell conditions specialized to modulus 2^128."""
    return math.gcd(increment, MODULUS) == 1 and (multiplier - 1) % 4 == 0


def recover_parameters(outputs: tuple[int, int, int]) -> tuple[int, int]:
    """Recover a and c from three complete consecutive outputs."""
    x0, x1, x2 = outputs
    d0 = (x1 - x0) % MODULUS
    d1 = (x2 - x1) % MODULUS
    recovered_a = (d1 * pow(d0, -1, MODULUS)) % MODULUS
    recovered_c = (x1 - recovered_a * x0) % MODULUS
    return recovered_a, recovered_c


def run_self_tests() -> None:
    assert has_full_period_conditions(MULTIPLIER, INCREMENT)
    assert not has_full_period_conditions(MULTIPLIER + 1, INCREMENT)
    assert not has_full_period_conditions(MULTIPLIER, INCREMENT + 1)

    seed = 0x0123456789ABCDEF0011223344556677
    states = generate_states(seed, 4)
    recovered_a, recovered_c = recover_parameters(tuple(states[:3]))
    assert recovered_a == MULTIPLIER
    assert recovered_c == INCREMENT
    assert lcg_next(states[2], recovered_a, recovered_c) == states[3]
    print("Baseline self-tests passed")


def run_trials(trials: int, output_path: Path) -> list[dict]:
    rng = random.Random(EXPERIMENT_SEED)
    rows = []

    for trial in range(1, trials + 1):
        seed = rng.randrange(MODULUS)
        states = generate_states(seed, 4)
        start = time.perf_counter_ns()
        recovered_a, recovered_c = recover_parameters(tuple(states[:3]))
        predicted = lcg_next(states[2], recovered_a, recovered_c)
        elapsed = time.perf_counter_ns() - start
        rows.append(
            {
                "trial": trial,
                "experiment_seed": EXPERIMENT_SEED,
                "victim_seed_hex": f"{seed:032x}",
                "recovery_ns": elapsed,
                "multiplier_recovered": recovered_a == MULTIPLIER,
                "increment_recovered": recovered_c == INCREMENT,
                "prediction_correct": predicted == states[3],
                "success": (
                    recovered_a == MULTIPLIER
                    and recovered_c == INCREMENT
                    and predicted == states[3]
                ),
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=1000)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        run_self_tests()
        return

    rows = run_trials(args.trials, args.output)
    times = [row["recovery_ns"] for row in rows]
    successes = sum(row["success"] for row in rows)
    print(f"Complete-output attacks: {successes}/{len(rows)} successful")
    print(f"Mean recovery time: {statistics.mean(times) / 1e6:.4f} ms")
    print(f"Median recovery time: {statistics.median(times) / 1e6:.4f} ms")
    print(f"Raw results: {args.output}")


if __name__ == "__main__":
    main()
