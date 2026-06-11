# PollubThink TORCS Racing Bot

This repository contains a Python controller for **TORCS** (The Open Racing Car
Simulator). The bot reads TORCS sensor data through the `snakeoil3` client,
drives the car with a rule-based racing controller, and uses Optuna to tune
selected steering, braking, speed, and vision parameters.

The project is designed for Windows. The `torcs/` directory contains the TORCS
game files used by the project, including `wtorcs.exe`, tracks, cars, and runtime
configuration. It is included in the repository to make setup repeatable and to
allow the training scripts to start TORCS automatically without requiring a
separate simulator installation.

## Requirements

- Windows
- Python 3.10 or newer
- Python packages from `requirements.txt`

## Setup

```powershell
git clone <repo-url>
cd IBM-Racing-League-PollubThink

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

The first clone can take a few minutes because the bundled TORCS directory is
about 520 MB.

## Running A Race

```powershell
python startup.py
```

`startup.py` closes previous TORCS instances, launches the bundled simulator,
navigates the game menus, and starts `my_racer.py`.

## Optimizing Parameters

For a short smoke run:

```powershell
$env:SMOKE = "1"
python optimize.py
```

For a full optimization run:

```powershell
$env:SMOKE = "0"
python optimize.py
```

Optimization progress is stored in `optuna_corkscrew.db`, so interrupted runs can
be resumed by running the same command again. The best runtime parameters are
written to `params.json`; `my_racer.py` loads this file automatically when it is
present.

To inspect an existing Optuna study:

```powershell
python inspect_study.py smoke_v1
python inspect_study.py car1ow1_v1
```

## Repository Layout

- `my_racer.py` - main driving controller.
- `startup.py` - TORCS launcher and bot startup script.
- `optimize.py` - Optuna training and parameter tuning loop.
- `inspect_study.py` - small utility for reviewing Optuna study results.
- `logger.py` - CSV lap and telemetry logging helpers.
- `params/` - baseline, best, and snapshot parameter files.
- `torcs/` - bundled TORCS simulator files used by the launcher and trainer.

See `params/PARAMS.md` for the parameter reference and tuning notes.
