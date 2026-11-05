"""Standalone truncated-LCG cryptanalysis project.

This file imports no other project file. It contains the complete attack,
exact educational LLL implementation, Babai nearest-plane recovery, unit
checks, randomized trials, experiment matrix, and artificial reset-code demo.
Only Python standard-library modules are required.
"""

import argparse
import csv
import hashlib
import json
import math
import platform
import random
import statistics
import sys
import time
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path


STATE_BITS = 128
MODULUS = 1 << STATE_BITS
MULTIPLIER = 6_364_136_223_846_793_005
INCREMENT = 1_442_695_040_888_963_407
EXPERIMENT_SEED = 20_261_030
MAIN_VISIBLE_BITS = 24
MAIN_HIDDEN_BITS = STATE_BITS - MAIN_VISIBLE_BITS
MAIN_OBSERVATIONS = 6
VISIBLE_BITS_OPTIONS = [16, 24, 32, 48, 64]
OBSERVATION_OPTIONS = [3, 4, 5, 6, 7, 8, 9]
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "results"


def dot(left: list, right: list):
    return sum(x * y for x, y in zip(left, right))


def gram_schmidt(basis: list[list[int]]):
    """Return exact orthogonal helpers, projection coefficients, and norms."""
    dimension = len(basis)
    orthogonal = []
    coefficients = [
        [Fraction(0) for _ in range(dimension)] for _ in range(dimension)
    ]
    squared_norms = []

    for i, basis_vector in enumerate(basis):
        current = [Fraction(value) for value in basis_vector]
        for j in range(i):
            projection = dot(basis_vector, orthogonal[j]) / squared_norms[j]
            coefficients[i][j] = projection
            current = [
                value - projection * component
                for value, component in zip(current, orthogonal[j])
            ]
        orthogonal.append(current)
        squared_norms.append(dot(current, current))
    return orthogonal, coefficients, squared_norms


def lll_reduce(
    original_basis: list[list[int]], delta: Fraction = Fraction(3, 4)
) -> list[list[int]]:
    """Educational exact-arithmetic LLL reduction."""
    basis = [row.copy() for row in original_basis]
    k = 1
    while k < len(basis):
        orthogonal, coefficients, squared_norms = gram_schmidt(basis)
        for j in range(k - 1, -1, -1):
            nearest_integer = round(coefficients[k][j])
            if nearest_integer:
                basis[k] = [
                    value - nearest_integer * earlier
                    for value, earlier in zip(basis[k], basis[j])
                ]
                orthogonal, coefficients, squared_norms = gram_schmidt(basis)
        right_side = (
            delta - coefficients[k][k - 1] ** 2
        ) * squared_norms[k - 1]
        if squared_norms[k] >= right_side:
            k += 1
        else:
            basis[k], basis[k - 1] = basis[k - 1], basis[k]
            k = max(k - 1, 1)
    return basis


def babai_closest_vector(
    reduced_basis: list[list[int]], target: list[int]
) -> list[int]:
    """Find a nearby lattice point using Babai nearest plane."""
    orthogonal, _, squared_norms = gram_schmidt(reduced_basis)
    remainder = [Fraction(value) for value in target]
    lattice_point = [0 for _ in target]
    for i in range(len(reduced_basis) - 1, -1, -1):
        coefficient = round(dot(remainder, orthogonal[i]) / squared_norms[i])
        lattice_point = [
            value + coefficient * component
            for value, component in zip(lattice_point, reduced_basis[i])
        ]
        remainder = [
            value - coefficient * component
            for value, component in zip(remainder, reduced_basis[i])
        ]
    return lattice_point


def lcg_next(state: int) -> int:
    return (MULTIPLIER * state + INCREMENT) % MODULUS


def generate_states(seed: int, count: int) -> list[int]:
    states = []
    state = seed
    for _ in range(count):
        state = lcg_next(state)
        states.append(state)
    return states


def visible_high_bits(state: int, visible_bits: int) -> int:
    return state >> (STATE_BITS - visible_bits)


def build_lcg_lattice(dimension: int) -> list[list[int]]:
    """Build sequences satisfying Z[i] = a^i Z[0] modulo m."""
    basis = [[pow(MULTIPLIER, i, MODULUS) for i in range(dimension)]]
    for coordinate in range(1, dimension):
        modulus_vector = [0] * dimension
        modulus_vector[coordinate] = MODULUS
        basis.append(modulus_vector)
    return basis


def increment_offsets(count: int) -> list[int]:
    offsets = [0]
    for _ in range(1, count):
        offsets.append((MULTIPLIER * offsets[-1] + INCREMENT) % MODULUS)
    return offsets


def prepare_attack(observation_count: int) -> dict:
    """Reusable work depending on public parameters, not a victim seed."""
    start = time.perf_counter_ns()
    reduced_basis = lll_reduce(build_lcg_lattice(observation_count))
    elapsed_ns = time.perf_counter_ns() - start
    return {
        "basis": reduced_basis,
        "offsets": increment_offsets(observation_count),
        "precomputation_ns": elapsed_ns,
    }


def recover_states(
    observations: list[int], visible_bits: int, prepared: dict
) -> tuple[list[int], list[int]]:
    """Recover complete states from public data and truncated outputs."""
    hidden_bits = STATE_BITS - visible_bits
    scaled = [value << hidden_bits for value in observations]
    target = [
        known - offset
        for known, offset in zip(scaled, prepared["offsets"])
    ]
    transformed = babai_closest_vector(prepared["basis"], target)
    states = [
        (value + offset) % MODULUS
        for value, offset in zip(transformed, prepared["offsets"])
    ]
    hidden_errors = [state - known for state, known in zip(states, scaled)]
    return states, hidden_errors


def validate_candidate(
    states: list[int], observations: list[int], visible_bits: int
) -> dict:
    hidden_bits = STATE_BITS - visible_bits
    scaled = [value << hidden_bits for value in observations]
    errors = [state - known for state, known in zip(states, scaled)]
    bounded = all(0 <= error < (1 << hidden_bits) for error in errors)
    reproduced = [visible_high_bits(state, visible_bits) for state in states]
    recurrence_valid = all(
        lcg_next(states[i]) == states[i + 1]
        for i in range(len(states) - 1)
    )
    return {
        "bounded": bounded,
        "reproduced": reproduced == observations,
        "recurrence_valid": recurrence_valid,
        "errors": errors,
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_main_trials(trials: int = 100) -> list[dict]:
    prepared = prepare_attack(MAIN_OBSERVATIONS)
    rng = random.Random(EXPERIMENT_SEED)
    rows = []
    for trial in range(1, trials + 1):
        seed = rng.randrange(MODULUS)
        actual = generate_states(seed, MAIN_OBSERVATIONS + 1)
        observations = [
            visible_high_bits(state, MAIN_VISIBLE_BITS)
            for state in actual[:MAIN_OBSERVATIONS]
        ]
        start = time.perf_counter_ns()
        recovered, _ = recover_states(observations, MAIN_VISIBLE_BITS, prepared)
        recovery_ns = time.perf_counter_ns() - start
        validation = validate_candidate(recovered, observations, MAIN_VISIBLE_BITS)
        predicted = visible_high_bits(lcg_next(recovered[-1]), MAIN_VISIBLE_BITS)
        actual_held_out = visible_high_bits(actual[-1], MAIN_VISIBLE_BITS)
        exact = recovered == actual[:MAIN_OBSERVATIONS]
        held_out = predicted == actual_held_out
        rows.append(
            {
                "trial": trial,
                "experiment_seed": EXPERIMENT_SEED,
                "victim_seed_hex": f"{seed:032x}",
                "state_bits": STATE_BITS,
                "visible_bits": MAIN_VISIBLE_BITS,
                "hidden_bits": MAIN_HIDDEN_BITS,
                "observations_used": MAIN_OBSERVATIONS,
                "precomputation_ns": prepared["precomputation_ns"],
                "recovery_ns": recovery_ns,
                "bounded_hidden_errors": validation["bounded"],
                "reproduced_observations": validation["reproduced"],
                "recurrence_valid": validation["recurrence_valid"],
                "exact_state_recovery": exact,
                "held_out_match": held_out,
                "success": exact and held_out,
            }
        )
    write_csv(RESULTS_DIR / "main_104_hidden_bits_trials.csv", rows)
    return rows


def run_matrix(trials_per_configuration: int = 30) -> tuple[list[dict], list[dict]]:
    rng = random.Random(EXPERIMENT_SEED)
    paired_seeds = [rng.randrange(MODULUS) for _ in range(trials_per_configuration)]
    prepared_by_count = {
        count: prepare_attack(count) for count in OBSERVATION_OPTIONS
    }
    raw_rows = []

    for visible_bits in VISIBLE_BITS_OPTIONS:
        hidden_bits = STATE_BITS - visible_bits
        for observation_count in OBSERVATION_OPTIONS:
            prepared = prepared_by_count[observation_count]
            for trial, seed in enumerate(paired_seeds, start=1):
                actual = generate_states(seed, observation_count + 1)
                observations = [
                    visible_high_bits(state, visible_bits)
                    for state in actual[:observation_count]
                ]
                start = time.perf_counter_ns()
                recovered, _ = recover_states(observations, visible_bits, prepared)
                recovery_ns = time.perf_counter_ns() - start
                validation = validate_candidate(recovered, observations, visible_bits)
                predicted = visible_high_bits(lcg_next(recovered[-1]), visible_bits)
                actual_held_out = visible_high_bits(actual[-1], visible_bits)
                exact = recovered == actual[:observation_count]
                held_out = predicted == actual_held_out
                raw_rows.append(
                    {
                        "visible_bits": visible_bits,
                        "hidden_bits": hidden_bits,
                        "observations_used": observation_count,
                        "nominal_visible_bits_total": visible_bits * observation_count,
                        "trial": trial,
                        "experiment_seed": EXPERIMENT_SEED,
                        "victim_seed_hex": f"{seed:032x}",
                        "precomputation_ns": prepared["precomputation_ns"],
                        "recovery_ns": recovery_ns,
                        "bounded_hidden_errors": validation["bounded"],
                        "reproduced_observations": validation["reproduced"],
                        "recurrence_valid": validation["recurrence_valid"],
                        "exact_state_recovery": exact,
                        "held_out_match": held_out,
                        "success": exact and held_out,
                    }
                )

    summaries = []
    for visible_bits in VISIBLE_BITS_OPTIONS:
        for observation_count in OBSERVATION_OPTIONS:
            rows = [
                row for row in raw_rows
                if row["visible_bits"] == visible_bits
                and row["observations_used"] == observation_count
            ]
            times = [row["recovery_ns"] for row in rows]
            successes = sum(row["success"] for row in rows)
            summaries.append(
                {
                    "visible_bits": visible_bits,
                    "hidden_bits": STATE_BITS - visible_bits,
                    "observations_used": observation_count,
                    "nominal_visible_bits_total": visible_bits * observation_count,
                    "trials": len(rows),
                    "exact_recoveries": sum(row["exact_state_recovery"] for row in rows),
                    "held_out_matches": sum(row["held_out_match"] for row in rows),
                    "successes": successes,
                    "success_rate": successes / len(rows),
                    "precomputation_ms": rows[0]["precomputation_ns"] / 1e6,
                    "mean_recovery_ms": statistics.mean(times) / 1e6,
                    "median_recovery_ms": statistics.median(times) / 1e6,
                    "minimum_recovery_ms": min(times) / 1e6,
                    "maximum_recovery_ms": max(times) / 1e6,
                }
            )

    write_csv(RESULTS_DIR / "attack_matrix_raw.csv", raw_rows)
    write_csv(RESULTS_DIR / "attack_matrix_summary.csv", summaries)
    return raw_rows, summaries


def reset_code_demo() -> str:
    """Run a local prediction attack without exposing service state to attacker code."""
    service_state = 0xA2748D16430F55E4D89739CA97557F36
    issued = []

    def service_issue(username: str) -> str:
        nonlocal service_state
        service_state = lcg_next(service_state)
        code = f"{visible_high_bits(service_state, MAIN_VISIBLE_BITS):06x}"
        issued.append((username, code))
        return code

    prepared = prepare_attack(MAIN_OBSERVATIONS)
    attacker_codes = [service_issue("attacker@example.test") for _ in range(6)]
    observations = [int(code, 16) for code in attacker_codes]
    recovered, _ = recover_states(observations, MAIN_VISIBLE_BITS, prepared)
    validation = validate_candidate(recovered, observations, MAIN_VISIBLE_BITS)
    assert validation["bounded"] and validation["reproduced"]
    predicted = f"{visible_high_bits(lcg_next(recovered[-1]), MAIN_VISIBLE_BITS):06x}"
    actual = service_issue("victim@example.test")
    lines = [
        "RESET-CODE PREDICTION DEMO",
        "",
        "Codes observed through the attacker's own account:",
        *[f"  {index}: {code}" for index, code in enumerate(attacker_codes, start=1)],
        "",
        f"Prediction committed before victim request: {predicted}",
        f"Victim code issued afterward:              {actual}",
        f"Attack successful:                         {predicted == actual}",
        "",
        "Assumptions: one shared global LCG, public parameters, consecutive outputs,",
        "and no intervening request between the attacker's final observation and victim.",
    ]
    transcript = "\n".join(lines)
    (RESULTS_DIR / "demo_transcript.txt").write_text(transcript + "\n", encoding="utf-8")
    assert predicted == actual
    return transcript


def run_self_tests() -> None:
    # Decomposition and recurrence tests.
    toy_m, toy_a, toy_c = 256, 5, 1
    toy_states = []
    toy_state = 123
    for _ in range(5):
        toy_state = (toy_a * toy_state + toy_c) % toy_m
        toy_states.append(toy_state)
    assert toy_states == [104, 9, 46, 231, 132]
    assert [(state >> 4, state & 15) for state in toy_states[:4]] == [
        (6, 8), (0, 9), (2, 14), (14, 7)
    ]

    # The transformed toy sequence follows multiplication without c.
    offsets = [0, 1, 6, 31]
    transformed = [(state - offset) % 256 for state, offset in zip(toy_states, offsets)]
    assert transformed == [104, 8, 40, 200]
    assert all((5 * transformed[i]) % 256 == transformed[i + 1] for i in range(3))

    # Toy lattice and Babai recovery.
    toy_basis = [[1, 5, 25, 125], [0, 256, 0, 0], [0, 0, 256, 0], [0, 0, 0, 256]]
    toy_target = [96, -1, 26, 193]
    toy_recovered = babai_closest_vector(lll_reduce(toy_basis), toy_target)
    assert toy_recovered == [104, 8, 40, 200]

    # Fixed 128-bit truncated recovery and held-out prediction.
    seed = 0x0123456789ABCDEF0011223344556677
    actual = generate_states(seed, MAIN_OBSERVATIONS + 1)
    observations = [visible_high_bits(state, MAIN_VISIBLE_BITS) for state in actual[:6]]
    prepared = prepare_attack(6)
    recovered, _ = recover_states(observations, MAIN_VISIBLE_BITS, prepared)
    validation = validate_candidate(recovered, observations, MAIN_VISIBLE_BITS)
    assert recovered == actual[:6]
    assert validation["bounded"] and validation["reproduced"] and validation["recurrence_valid"]
    assert visible_high_bits(lcg_next(recovered[-1]), MAIN_VISIBLE_BITS) == visible_high_bits(actual[-1], MAIN_VISIBLE_BITS)
    print("Truncated-attack self-tests passed")


def write_environment_and_manifest() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    metadata = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "implementation": platform.python_implementation(),
        "state_bits": STATE_BITS,
        "modulus": str(MODULUS),
        "multiplier": str(MULTIPLIER),
        "increment": str(INCREMENT),
        "experiment_seed": EXPERIMENT_SEED,
        "main_visible_bits": MAIN_VISIBLE_BITS,
        "main_hidden_bits": MAIN_HIDDEN_BITS,
        "main_observations": MAIN_OBSERVATIONS,
        "matrix_visible_bits": VISIBLE_BITS_OPTIONS,
        "matrix_observations": OBSERVATION_OPTIONS,
        "dependencies": "Python standard library only",
    }
    (RESULTS_DIR / "environment.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )

    files = {}
    for path in sorted(RESULTS_DIR.iterdir()):
        if path.is_file() and path.name != "manifest.json":
            files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {"sha256": files}
    (RESULTS_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def print_main_summary(rows: list[dict]) -> None:
    times = [row["recovery_ns"] for row in rows]
    print(f"Main attack: {sum(row['success'] for row in rows)}/{len(rows)} exact recoveries")
    print(f"Reusable LLL preparation: {rows[0]['precomputation_ns'] / 1e6:.3f} ms")
    print(f"Mean per-victim recovery: {statistics.mean(times) / 1e6:.3f} ms")


def print_matrix(summary: list[dict]) -> None:
    print("\nSuccesses out of 30 paired trials")
    print("visible\\obs", *[f"{count:>7}" for count in OBSERVATION_OPTIONS])
    for visible_bits in VISIBLE_BITS_OPTIONS:
        cells = []
        for count in OBSERVATION_OPTIONS:
            row = next(
                item for item in summary
                if item["visible_bits"] == visible_bits
                and item["observations_used"] == count
            )
            cells.append(f"{row['successes']:>7}")
        print(f"{visible_bits:>11}", *cells)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=["self-test", "main-trials", "matrix", "demo", "all"],
        nargs="?",
        default="all",
    )
    parser.add_argument("--main-trials", type=int, default=100)
    parser.add_argument("--matrix-trials", type=int, default=30)
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.command == "self-test":
        run_self_tests()
        return
    if args.command == "main-trials":
        rows = run_main_trials(args.main_trials)
        print_main_summary(rows)
        write_environment_and_manifest()
        return
    if args.command == "matrix":
        _, summary = run_matrix(args.matrix_trials)
        print_matrix(summary)
        write_environment_and_manifest()
        return
    if args.command == "demo":
        print(reset_code_demo())
        write_environment_and_manifest()
        return

    run_self_tests()
    rows = run_main_trials(args.main_trials)
    print_main_summary(rows)
    _, summary = run_matrix(args.matrix_trials)
    print_matrix(summary)
    print("\n" + reset_code_demo())
    write_environment_and_manifest()
    print(f"\nResults written to {RESULTS_DIR}")


if __name__ == "__main__":
    main()
