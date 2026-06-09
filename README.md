# TORCS AI Racing Bot (Optuna Tuning + Dynamic Lines)

This project features an advanced, modular racing bot for the **TORCS** (The Open Racing Car Simulator) engine. It is built on top of the `gym_torcs` infrastructure and client-server architecture (`snakeoil3`).

Instead of relying heavily on hardcoded rules, the bot utilizes **Bayesian Optimization (TPE)** to find the ideal corner entry parameters and dynamically generates racing lines through a technique called Apex Shifting.

## 📂 Key Files:

- `my_racer.py` - The main "brain" of the bot. Contains logic for reading sensors, trail braking, acceleration, and shifting.
- `optimize.py` - The training script. Runs the physics engine in accelerated mode (x128) and uses the Optuna library to search for perfect racing parameters.
- `startup.py` - Game launcher and manager. Cleans up dangling background processes, automatically navigates game menus, and deploys the bot.
- `logger.py` - Telemetry system that logs lap results to CSV files.

## 🚀 Requirements

- **Python 3.10+** (tested up to 3.14, fully backwards compatible with 3.10/3.11/3.12)
- **Windows OS** (The bundled TORCS engine is the `wtorcs.exe` binary; PyAutoGUI utilizes WinAPI to simulate keystrokes for menu navigation).
- Python libraries listed in `requirements.txt`.

### Setup from scratch (e.g., after `git clone` on a new machine)

```powershell
git clone <repo-url>
cd IBM-TORCS-Think2

# (Optional) Virtual environment setup
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

The TORCS engine (`torcs/wtorcs.exe` + tracks + cars, ~520 MB) is committed to the repo,
so everything is ready after `git clone` — no external TORCS installation is needed.

> **NOTE — the first `git clone` will take a few minutes** due to the 520 MB TORCS engine.

## 🎮 How to run?

### Option 1: Standard race (Testing)

To see the bot in action on the track without modifying parameters, simply use the startup script. It will automatically launch the game and press the appropriate keys in the menu:

```bash
python startup.py
```

### Option 2: Optimization Process (Time hunting)

To put the bot into learning mode, launch the AI module. The bot will run a specified number of trials, autonomously restarting the environment after every error or crash, aiming to shave fractions of a second off the lap time:

```powershell
# Full run (Phase 3 from PLAN.md) - 500 trials, ~8-12h, overnight
$env:SMOKE = "0"
python optimize.py

# Smoke run (Phase 2) - 20 trials, +/-20% around baseline, ~20-30 min
$env:SMOKE = "1"
python optimize.py
```

The best obtained genes will be saved to the `params.json` file, after which `my_racer.py` will automatically load them during subsequent runs.

Progress is persisted in `optuna_corkscrew.db` (SQLite) — Ctrl+C is safe, re-running the same command continues from the last completed trial (`load_if_exists=True`).

### Option 3: View statistics of an existing study

```powershell
python inspect_study.py smoke_v1     # after Phase 2
python inspect_study.py car1ow1_v1   # after Phase 3
```

Shows the number of completed trials, DNF count, top-5 times, and best params.

---

**Note:** The architecture includes environment safeguards that, in the event of an internal game server crash (typical for very fast computations on Windows), will automatically force a restart of the TORCS instance and resume training.
