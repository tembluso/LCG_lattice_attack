# Predicting a Truncated 128-bit LCG with Lattices

This repository contains the code, experimental results, figures, and report for
an Applied Cryptography mini-project. It demonstrates that a full-period
128-bit linear congruential generator (LCG) is still predictable when only the
most significant bits of consecutive states are exposed.

In the main experiment, every output reveals 24 bits and hides 104 bits. Six
consecutive outputs are used to recover the internal state with lattice
reduction and Babai's nearest-plane algorithm. The recovered state then predicts
a held-out seventh output that was not used during recovery.

All cryptanalysis and verification scripts are self-contained, use only the
Python standard library, and do not import code from one another. The optional
browser-based presentation demo uses Streamlit and contains its own standalone
copy of the attack.

## Requirements

- Python 3.11 or later
- No third-party packages for the cryptanalysis, experiments, or verification
- Streamlit only for the optional interactive browser demo

The supplied results were generated with Python 3.14.3 on Windows. The exact
environment is recorded in [`results/environment.json`](results/environment.json).

## Interactive Streamlit demo

The browser demo presents the attack in four controlled stages: observe six
codes, recover the hidden states, commit to a prediction, and request the victim
code. It executes the real LLL/Babai recovery and does not reveal the artificial
service state to the attacker logic.

Create a virtual environment and install the optional demo dependency:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Start the app from the repository root:

```powershell
python -m streamlit run app.py
```

On macOS or Linux, activate the environment with `source .venv/bin/activate`.
Streamlit opens the visualizer at `http://localhost:8501`. For a presentation,
start it before entering slideshow mode and switch directly between PowerPoint
and the already-open browser window.

The **Run complete attack** button provides a quick check. For the presentation,
use the four numbered buttons so the prediction remains visibly committed before
the victim requests a code.

The sidebar also provides four profiles drawn from the saved experiment matrix:

- **Main project:** 24 visible bits, 104 hidden bits, and 6 observations
- **Medium leakage:** 32 visible bits and 5 observations
- **Heavy leakage:** 48 visible bits and 3 observations
- **Low leakage:** 16 visible bits and 9 observations

Every profile achieved 100% recovery in the recorded trials. The low-leakage
profile uses a nine-dimensional exact LLL reduction and may take roughly 10–15
seconds depending on the computer. Changing profile resets the staged demo so
outputs from different configurations are never mixed.

## Quick demo

From the repository root, run:

```powershell
python .\code\02_truncated_lcg_project.py demo
```

On macOS or Linux, the equivalent command is:

```bash
python3 ./code/02_truncated_lcg_project.py demo
```

The script simulates an artificial reset-code service using one shared LCG. An
attacker requests six codes through their own account, recovers the generator's
state, and commits to a prediction **before** the victim requests another code.
The final two lines compare the committed prediction with the code subsequently
issued to the victim:

```text
Prediction committed before victim request: <predicted code>
Victim code issued afterward:              <actual code>
Attack successful:                         True
```

The scenario is deliberately local and artificial; it does not contact or
attack any real service. Its assumptions are a shared global LCG, known public
LCG parameters, consecutive observable outputs, and no intervening request
before the victim's code.

## Reproduce and verify the complete project

To regenerate all machine-readable experiment results and then independently
check them, run this from the repository root:

```powershell
python .\code\03_verify_project.py --full
```

On macOS or Linux:

```bash
python3 ./code/03_verify_project.py --full
```

The `--full` run:

1. executes both standalone self-test suites;
2. generates 1,000 complete-output baseline trials;
3. generates 100 trials of the main 24-visible/104-hidden-bit attack;
4. generates the 1,050-trial leakage/observation matrix;
5. runs the reset-code prediction demonstration;
6. records environment metadata and SHA-256 hashes; and
7. verifies the CSV schemas, trial counts, success totals, boundary results,
   transcript, and manifest.

Expected runtime is approximately one minute on the development machine. LLL
timings vary with the computer and Python version. A successful run ends with:

```text
All result files and boundary checks passed
```

To verify the committed result files without regenerating them, omit `--full`:

```powershell
python .\code\03_verify_project.py
```

## Other useful commands

```powershell
# Full-output LCG baseline
python .\code\01_complete_output_baseline.py --self-test
python .\code\01_complete_output_baseline.py

# Truncated-LCG self-tests and individual experiments
python .\code\02_truncated_lcg_project.py self-test
python .\code\02_truncated_lcg_project.py main-trials
python .\code\02_truncated_lcg_project.py matrix
python .\code\02_truncated_lcg_project.py demo

# Run every experiment implemented by the main attack script
python .\code\02_truncated_lcg_project.py all
```

## Repository contents

- [`code/01_complete_output_baseline.py`](code/01_complete_output_baseline.py):
  recovery from three complete consecutive outputs
- [`code/02_truncated_lcg_project.py`](code/02_truncated_lcg_project.py):
  standalone lattice attack, experiments, and reset-code demo
- [`code/03_verify_project.py`](code/03_verify_project.py): regeneration and
  independent artifact verification
- [`app.py`](app.py): standalone interactive Streamlit attack visualizer
- [`requirements.txt`](requirements.txt): optional Streamlit dependency
- [`results/`](results/): raw trials, summaries, demo transcript, environment
  metadata, and integrity manifest
- [`figures/`](figures/): the recovery-boundary result and an explanatory
  visible/hidden-bit diagram
- [`PROJECT_REPORT.md`](PROJECT_REPORT.md): threat model, mathematics,
  methodology, results, limitations, and references

## Main result

The main 24-visible/104-hidden-bit configuration succeeded in 100 out of 100
recorded trials. This is stronger evidence than merely describing the generator
as "128-bit": the attack reconstructs 104 hidden state bits from six related
truncated outputs and correctly predicts an unseen output.

The repository also reports unsuccessful configurations. Revealing enough bits
provides theoretical information capacity, but it does not by itself guarantee
unique recovery: transcripts can collide, and Babai's nearest-plane method is
approximate. See the report and the recovery-boundary figure for the complete
interpretation.

## Scope and ethics

- Public information: modulus, multiplier, increment, recurrence, truncation
  format, and output order
- Secret information: internal state and the hidden low bits
- Attacker capability: observe consecutive most-significant-bit outputs
- Test environment: local artificial generator and artificial accounts only

The results apply to the stated parameters and tested configurations. They do
not prove that every truncated LCG is recoverable, and they do not imply a
weakness in cryptographically secure random number generators.
