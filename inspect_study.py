"""Szybki podglad statystyk istniejacego badania Optuny bez odpalania nowych prob."""
import optuna
import sys

STORAGE = "sqlite:///optuna_corkscrew.db"
STUDY_NAME = sys.argv[1] if len(sys.argv) > 1 else "smoke_v1"

study = optuna.load_study(study_name=STUDY_NAME, storage=STORAGE)

trials = study.trials
completed = [t for t in trials if t.state.name == "COMPLETE"]
lap = sorted(t.value for t in completed if t.value is not None and t.value <= 200.0)
dnf = [t for t in completed if t.value is not None and t.value > 200.0]

print(f"Study: {STUDY_NAME}")
print(f"Total trials: {len(trials)}, completed: {len(completed)}")
print(f"  Lap-finishing: {len(lap)} / DNF: {len(dnf)}  (DNF rate: {len(dnf)/max(1,len(completed))*100:.1f}%)")
if lap:
    print(f"  Lap times: min={lap[0]:.3f}s, mean={sum(lap)/len(lap):.3f}s, max={lap[-1]:.3f}s")
    print(f"  Best 5: {[f'{v:.3f}' for v in lap[:5]]}")
if study.best_trial:
    print(f"\nBest trial #{study.best_trial.number}: {study.best_value:.3f} s")
    for k, v in study.best_params.items():
        print(f"  {k}: {v:.4f}")
