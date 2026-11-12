"""Interactive Streamlit visualizer for the truncated-LCG attack.

This file is intentionally standalone: it does not import another project file.
The four presentation stages execute the real LLL/Babai recovery used by the
command-line project, while keeping the artificial service state separate from
the values available to the attacker.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from fractions import Fraction

import streamlit as st


STATE_BITS = 128
MODULUS = 1 << STATE_BITS
MULTIPLIER = 6_364_136_223_846_793_005
INCREMENT = 1_442_695_040_888_963_407
VISIBLE_BITS = 24
HIDDEN_BITS = STATE_BITS - VISIBLE_BITS
OBSERVATIONS = 6
DEFAULT_SERVICE_SEED = 0xA2748D16430F55E4D89739CA97557F36
ATTACK_PROFILES = {
    "Main project · 24 visible bits / 6 codes": (24, 6),
    "Medium leakage · 32 visible bits / 5 codes": (32, 5),
    "Heavy leakage · 48 visible bits / 3 codes": (48, 3),
    "Low leakage (slow) · 16 visible bits / 9 codes": (16, 9),
}


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
    """Reduce a lattice basis using exact-arithmetic educational LLL."""
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


def visible_high_bits(state: int) -> int:
    return state >> HIDDEN_BITS


def build_lcg_lattice(dimension: int) -> list[list[int]]:
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
    start = time.perf_counter_ns()
    reduced_basis = lll_reduce(build_lcg_lattice(observation_count))
    elapsed_ns = time.perf_counter_ns() - start
    return {
        "basis": reduced_basis,
        "offsets": increment_offsets(observation_count),
        "precomputation_ns": elapsed_ns,
    }


def recover_states(observations: list[int], prepared: dict) -> tuple[list[int], list[int]]:
    scaled = [value << HIDDEN_BITS for value in observations]
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


def validate_candidate(states: list[int], observations: list[int]) -> dict:
    scaled = [value << HIDDEN_BITS for value in observations]
    errors = [state - known for state, known in zip(states, scaled)]
    return {
        "bounded": all(0 <= error < (1 << HIDDEN_BITS) for error in errors),
        "reproduced": [visible_high_bits(state) for state in states] == observations,
        "recurrence_valid": all(
            lcg_next(states[index]) == states[index + 1]
            for index in range(len(states) - 1)
        ),
    }


def state_fingerprint(state: int) -> str:
    digest = hashlib.sha256(state.to_bytes(16, "big")).hexdigest()
    return f"{digest[:6]}…{digest[-6:]}"


def new_demo(service_seed: int) -> dict:
    return {
        "config": (VISIBLE_BITS, OBSERVATIONS),
        "initial_seed": service_seed,
        "service_state": service_seed,
        "issued": [],
        "stage": 0,
        "recovered": None,
        "validation": None,
        "precomputation_ms": None,
        "recovery_ms": None,
        "prediction": None,
        "victim_code": None,
    }


def service_issue(demo: dict, username: str) -> str:
    """Artificial service boundary: callers receive a code, never the state."""
    demo["service_state"] = lcg_next(demo["service_state"])
    hexadecimal_width = (VISIBLE_BITS + 3) // 4
    code = f"{visible_high_bits(demo['service_state']):0{hexadecimal_width}x}"
    demo["issued"].append(
        {"username": username, "code": code, "state": demo["service_state"]}
    )
    return code


def observe_codes(demo: dict) -> None:
    if demo["stage"] != 0:
        return
    for _ in range(OBSERVATIONS):
        service_issue(demo, "attacker@example.test")
    demo["stage"] = 1


def recover_generator(demo: dict) -> None:
    if demo["stage"] != 1:
        return
    observations = [int(item["code"], 16) for item in demo["issued"]]
    prepared = prepare_attack(OBSERVATIONS)
    start = time.perf_counter_ns()
    recovered, _ = recover_states(observations, prepared)
    recovery_ns = time.perf_counter_ns() - start
    validation = validate_candidate(recovered, observations)
    actual_states = [item["state"] for item in demo["issued"]]

    demo["recovered"] = recovered
    demo["validation"] = {
        **validation,
        "ground_truth_match": recovered == actual_states,
    }
    demo["precomputation_ms"] = prepared["precomputation_ns"] / 1e6
    demo["recovery_ms"] = recovery_ns / 1e6
    demo["stage"] = 2


def commit_prediction(demo: dict) -> None:
    if demo["stage"] != 2:
        return
    next_state = lcg_next(demo["recovered"][-1])
    hexadecimal_width = (VISIBLE_BITS + 3) // 4
    demo["prediction"] = f"{visible_high_bits(next_state):0{hexadecimal_width}x}"
    demo["stage"] = 3


def victim_request(demo: dict) -> None:
    if demo["stage"] != 3:
        return
    demo["victim_code"] = service_issue(demo, "victim@example.test")
    demo["stage"] = 4


def run_complete_attack(demo: dict) -> None:
    observe_codes(demo)
    recover_generator(demo)
    commit_prediction(demo)
    victim_request(demo)


def render_stage_card(number: int, title: str, description: str, stage: int) -> None:
    if stage >= number:
        css_class, marker = "done", "✓"
    elif stage + 1 == number:
        css_class, marker = "active", str(number)
    else:
        css_class, marker = "waiting", str(number)
    st.markdown(
        f"""
        <div class="stage-card {css_class}">
          <div class="stage-number">{marker}</div>
          <div class="stage-title">{title}</div>
          <div class="stage-description">{description}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


st.set_page_config(
    page_title="Truncated LCG Attack Visualizer",
    page_icon="🔓",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1500px;}
      [data-testid="stSidebar"] {border-right: 1px solid #26384b;}
      .hero-kicker {color: #5ea3e5; font-weight: 700; letter-spacing: .08em;
                    text-transform: uppercase; font-size: .82rem;}
      .hero-title {font-size: 2.75rem; font-weight: 800; line-height: 1.08;
                   color: #f7f9fc; margin: .25rem 0 .5rem 0;}
      .hero-copy {font-size: 1.05rem; color: #b8c7d6; max-width: 980px;}
      .stage-card {min-height: 142px; border: 1px solid #33495f; border-radius: 12px;
                   padding: 16px; background: #111f2d;}
      .stage-card.active {border: 2px solid #d97706; background: #241b10;}
      .stage-card.done {border: 1px solid #2f855a; background: #10251c;}
      .stage-card.waiting {opacity: .62;}
      .stage-number {display: inline-flex; width: 30px; height: 30px; border-radius: 7px;
                     align-items: center; justify-content: center; background: #2b6cb0;
                     color: white; font-weight: 800; margin-bottom: 10px;}
      .done .stage-number {background: #2f855a;}
      .active .stage-number {background: #d97706;}
      .stage-title {font-size: 1.05rem; font-weight: 750; color: #f7f9fc;}
      .stage-description {font-size: .86rem; color: #aebdca; margin-top: 5px;}
      .code-box {border: 1px solid #385573; border-radius: 10px; padding: 15px 10px;
                 background: #0c1824; text-align: center;}
      .code-label {font-size: .75rem; color: #8ca2b7; text-transform: uppercase;}
      .code-value {font-family: Consolas, monospace; font-size: 1.5rem; color: #f7f9fc;
                   font-weight: 750; letter-spacing: .05em;}
      .prediction-box {border: 2px solid #d97706; border-radius: 12px; padding: 22px;
                       text-align: center; background: #251a0c;}
      .prediction-value {font-family: Consolas, monospace; font-size: 2.4rem;
                         color: #f2a33a; font-weight: 800; letter-spacing: .08em;}
      .success-box {border: 2px solid #2f855a; border-radius: 12px; padding: 22px;
                    text-align: center; background: #0e271b; color: #83d6a5;}
      .small-note {font-size: .82rem; color: #8ca2b7;}
      div[data-testid="stMetric"] {background: #111f2d; border: 1px solid #2b4055;
                                   padding: 14px; border-radius: 10px;}
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.title("Attack controls")
    st.caption("The service state remains hidden. Only issued reset codes reach the attacker.")
    selected_profile = st.selectbox(
        "Attack profile",
        list(ATTACK_PROFILES),
        help="These profiles achieved 100% recovery in the project's saved experiment matrix.",
    )

VISIBLE_BITS, OBSERVATIONS = ATTACK_PROFILES[selected_profile]
HIDDEN_BITS = STATE_BITS - VISIBLE_BITS

if "demo" not in st.session_state:
    st.session_state.demo = new_demo(DEFAULT_SERVICE_SEED)
elif st.session_state.demo.get("config") != (VISIBLE_BITS, OBSERVATIONS):
    # A profile changes the lattice dimension and code format. Resetting avoids
    # mixing observations generated under incompatible configurations.
    st.session_state.demo = new_demo(DEFAULT_SERVICE_SEED)

demo = st.session_state.demo

with st.sidebar:
    st.metric("Generator", "128-bit LCG")
    st.metric("Visible per code", f"{VISIBLE_BITS} bits")
    st.metric("Hidden per state", f"{HIDDEN_BITS} bits")
    st.metric("Observations", OBSERVATIONS)
    if VISIBLE_BITS == 16:
        st.warning("The 9-dimensional exact LLL step may take around 10–15 seconds.")
    else:
        st.caption("Changing profile resets the four-stage demonstration.")

    st.divider()
    if st.button("Reset default scenario", use_container_width=True):
        st.session_state.demo = new_demo(DEFAULT_SERVICE_SEED)
        st.rerun()
    if st.button("Generate fresh scenario", use_container_width=True):
        st.session_state.demo = new_demo(secrets.randbits(STATE_BITS))
        st.rerun()

    st.divider()
    st.markdown("**Public to the attacker**")
    st.caption("Modulus, multiplier, increment, truncation format, and output order")
    st.markdown("**Never exposed**")
    st.caption(f"Internal service state and the {HIDDEN_BITS} hidden low bits")

st.markdown('<div class="hero-kicker">Applied Cryptography · Interactive demonstration</div>', unsafe_allow_html=True)
st.markdown('<div class="hero-title">Predicting reset codes from truncated LCG outputs</div>', unsafe_allow_html=True)
st.markdown(
    f'<div class="hero-copy">The attacker requests {OBSERVATIONS} codes through their own account, '
    'recovers the hidden generator state with LLL and Babai, commits to the next code, '
    'and only then allows the victim to request it.</div>',
    unsafe_allow_html=True,
)

st.write("")
stage_columns = st.columns(4)
stage_data = [
    (1, "Observe", f"Request {OBSERVATIONS} attacker codes"),
    (2, "Recover", "Solve the lattice problem"),
    (3, "Commit", "Store the unseen prediction"),
    (4, "Verify", "Issue the victim code"),
]
for column, (number, title, description) in zip(stage_columns, stage_data):
    with column:
        render_stage_card(number, title, description, demo["stage"])

st.write("")
button_columns = st.columns([1, 1, 1, 1, 1.35])
with button_columns[0]:
    observe_clicked = st.button(
        "1  Observe codes", disabled=demo["stage"] != 0, use_container_width=True
    )
with button_columns[1]:
    recover_clicked = st.button(
        "2  Recover state", disabled=demo["stage"] != 1, use_container_width=True
    )
with button_columns[2]:
    commit_clicked = st.button(
        "3  Commit prediction", disabled=demo["stage"] != 2, use_container_width=True
    )
with button_columns[3]:
    verify_clicked = st.button(
        "4  Victim requests", disabled=demo["stage"] != 3, use_container_width=True
    )
with button_columns[4]:
    full_clicked = st.button(
        "Run complete attack", disabled=demo["stage"] != 0, use_container_width=True,
        type="primary"
    )

if observe_clicked:
    observe_codes(demo)
if recover_clicked:
    with st.spinner("Reducing the public lattice and recovering the hidden states…"):
        recover_generator(demo)
if commit_clicked:
    commit_prediction(demo)
if verify_clicked:
    victim_request(demo)
if full_clicked:
    with st.spinner("Executing the complete attack…"):
        run_complete_attack(demo)
st.session_state.demo = demo

# The controls above were rendered using the stage at the start of this run.
# Rerun after an action so the newly available next step is enabled immediately.
if observe_clicked or recover_clicked or commit_clicked or verify_clicked or full_clicked:
    st.rerun()

st.divider()

if demo["stage"] == 0:
    st.info("Begin with **Observe codes**. The attacker has not received any service output yet.")

if demo["stage"] >= 1:
    st.subheader("Observed through the attacker's own account")
    code_columns = st.columns(min(OBSERVATIONS, 6))
    for index, (column, item) in enumerate(zip(code_columns, demo["issued"][:OBSERVATIONS]), start=1):
        with column:
            st.markdown(
                f'<div class="code-box"><div class="code-label">Code {index}</div>'
                f'<div class="code-value">{item["code"]}</div></div>',
                unsafe_allow_html=True,
            )
    if OBSERVATIONS > 6:
        code_columns = st.columns(OBSERVATIONS - 6)
        for index, (column, item) in enumerate(
            zip(code_columns, demo["issued"][6:OBSERVATIONS]), start=7
        ):
            with column:
                st.markdown(
                    f'<div class="code-box"><div class="code-label">Code {index}</div>'
                    f'<div class="code-value">{item["code"]}</div></div>',
                    unsafe_allow_html=True,
                )
    st.caption(
        f"The attacker receives these {VISIBLE_BITS}-bit hexadecimal codes only. "
        "The complete 128-bit states stay inside the artificial service."
    )

if demo["stage"] >= 2:
    st.subheader("Lattice recovery")
    metric_columns = st.columns(4)
    metric_columns[0].metric("Hidden per output", f"{HIDDEN_BITS} bits")
    metric_columns[1].metric("Candidate states", OBSERVATIONS)
    metric_columns[2].metric("Reusable LLL preparation", f"{demo['precomputation_ms']:.1f} ms")
    metric_columns[3].metric("Victim-specific recovery", f"{demo['recovery_ms']:.3f} ms")

    checks = demo["validation"]
    check_columns = st.columns(4)
    check_items = [
        ("Hidden errors bounded", checks["bounded"]),
        ("Outputs reproduced", checks["reproduced"]),
        ("Recurrence valid", checks["recurrence_valid"]),
        ("Demo ground truth", checks["ground_truth_match"]),
    ]
    for column, (label, passed) in zip(check_columns, check_items):
        column.success(f"✓ {label}" if passed else f"✗ {label}")

    with st.expander("Recovered state fingerprints"):
        st.caption("Fingerprints identify the recovered states without filling the screen with 128-bit integers.")
        state_columns = st.columns(min(OBSERVATIONS, 6))
        for index, (column, state) in enumerate(
            zip(state_columns, demo["recovered"][:6]), start=1
        ):
            column.code(f"X{index}\n{state_fingerprint(state)}", language=None)
        if OBSERVATIONS > 6:
            state_columns = st.columns(OBSERVATIONS - 6)
            for index, (column, state) in enumerate(
                zip(state_columns, demo["recovered"][6:]), start=7
            ):
                column.code(f"X{index}\n{state_fingerprint(state)}", language=None)

if demo["stage"] >= 3:
    st.subheader("Prediction committed before the victim request")
    st.markdown(
        f'<div class="prediction-box"><div class="code-label">Committed next code</div>'
        f'<div class="prediction-value">{demo["prediction"]}</div>'
        '<div class="small-note">No victim code exists yet at the moment of commitment.</div></div>',
        unsafe_allow_html=True,
    )

if demo["stage"] >= 4:
    st.subheader("Victim request and verification")
    comparison = st.columns(2)
    comparison[0].metric("Attacker prediction", demo["prediction"])
    comparison[1].metric("Victim code issued afterward", demo["victim_code"])
    success = demo["prediction"] == demo["victim_code"]
    if success:
        st.markdown(
            '<div class="success-box"><h2>Prediction matched</h2>'
            '<p>The attacker predicted the unseen victim code before the service issued it.</p></div>',
            unsafe_allow_html=True,
        )
    else:
        st.error("Prediction failed for this scenario.")

st.write("")
explanation_tabs = st.tabs(["Why it works", "Attack assumptions", "Secure replacement"])
with explanation_tabs[0]:
    st.markdown(
        f"""
        Each exposed value is the high part of a complete state:

        $$X_i = 2^{{{HIDDEN_BITS}}}Y_i + e_i, \\qquad 0 \\le e_i < 2^{{{HIDDEN_BITS}}}.$$

        The public recurrence connects the {OBSERVATIONS} bounded errors. LLL produces a
        shorter basis and Babai finds a nearby lattice point. The candidate is
        accepted only if it reproduces every observation and satisfies the LCG
        recurrence.
        """
    )
with explanation_tabs[1]:
    st.markdown(
        f"""
        - One shared global LCG issues consecutive codes.
        - The modulus, multiplier, increment, and truncation format are public.
        - The attacker can obtain {OBSERVATIONS} consecutive outputs through their own account.
        - No request intervenes between the final observation and the victim request.
        - The internal state and hidden low bits are never provided to attacker code.
        """
    )
with explanation_tabs[2]:
    st.markdown(
        """
        Real reset codes should come from an operating-system-backed CSPRNG and
        should be isolated per request, short-lived, single-use, and rate-limited.

        ```python
        import secrets
        secure_code = secrets.token_hex(3)
        ```

        A CSPRNG does not expose a public linear recurrence that lets an attacker
        reconstruct its internal state from consecutive outputs.
        """
    )

st.caption(
    "Local educational demonstration using artificial accounts and an artificial service. "
    "It does not contact or attack any external system."
)
