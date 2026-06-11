# Parameter Reference

This file summarizes the runtime parameters used by `my_racer.py` and the saved
parameter sets produced during Optuna tuning.

Default values are defined in the `PARAMS` dictionary in `my_racer.py`. When a
root-level `params.json` file exists, `my_racer.py` loads it and overrides the
defaults. `optimize.py` writes `params.json` after successful tuning runs.

## Directory Structure

```text
params/
|-- PARAMS.md
|-- baseline.json
|-- best/
|   |-- smoke_best.json
|   |-- full_best.json
|   |-- extended_best.json
|   |-- brakes_best.json
|   |-- brakes_ext_best.json
|   |-- vision_best.json
|   |-- joint_best.json
|   |-- antislalom_best.json
|   |-- abs_best.json
|   |-- joint_abs.json
|   `-- joint_abs2.json
`-- snapshots/
    |-- pre_phase6a.json
    |-- pre_phase6b.json
    |-- pre_phase6c.json
    |-- pre_phase6vision.json
    `-- pre_antislalom_run.json
```

- `baseline.json` keeps the original controller baseline.
- `best/` stores the best parameter sets from completed tuning stages.
- `snapshots/` stores rollback copies taken before selected tuning stages.
- `params.json` is not committed; it is the active local runtime config.

To restore the validated vision baseline:

```powershell
copy params\best\vision_best.json params.json
```

## Controller Parameters

| Parameter | Default | Purpose |
| --- | ---: | --- |
| `TARGET_STRAIGHT_SPEED` | 290.0 | Target speed on long straights. |
| `SAFE_SHARP_CORNER_SPEED` | 80.0 | Speed cap for sharp corners. |
| `MIN_NORMAL_CORNER_SPEED` | 85.0 | Minimum target speed for normal corners. |
| `STEER_GAIN` | 30.0 | Steering response multiplier for the car angle. |
| `CENTERING_GAIN` | 0.2 | Strength of the correction based on track position. |
| `BRAKE_THRESHOLD` | 0.3 | Speed overshoot threshold before braking starts. |
| `APEX_SHIFT_GAIN` | 0.46 | How strongly the target line shifts toward the apex. |
| `APEX_SCALE` | 0.4 | Smoothness scale for the apex shift tanh curve. |
| `BRAKE_DISTANCE_LIN` | 0.35 | Linear speed component in the safe braking distance. |
| `BRAKE_DISTANCE_QUAD` | 1200.0 | Quadratic speed divisor in the safe braking distance. |
| `TRAIL_BRAKE_DIVISOR` | 40.0 | Trail-braking forgiveness based on exit vision. |
| `BRAKE_PRESS_DIVISOR` | 50.0 | Brake-force divisor once the safe distance is exceeded. |
| `VISION_LONG_STRAIGHT` | 130.0 | Vision threshold for long straight detection. |
| `VISION_FAST_CORNER` | 90.0 | Vision threshold for fast corner speed. |
| `SPEED_FAST_CORNER` | 240.0 | Target speed for fast corners. |
| `VISION_MED_CORNER` | 60.0 | Vision threshold for medium corner speed. |
| `SPEED_MED_CORNER` | 190.0 | Target speed for medium corners. |
| `ABS_SLIP_THRESHOLD` | 3.0 | Wheel-slip threshold before ABS releases braking. |
| `ABS_MODULATION` | 0.4 | Brake release amount during ABS intervention. |
| `ABS_D_GAIN` | 0.1 | ABS derivative gain based on slip increase rate. |
| `STEER_D_GAIN` | 0.5 | Steering derivative gain used to reduce oscillation. |
| `TCS_SLIP_THRESHOLD` | 5.0 | Wheel-slip threshold for traction control. |

## Parameter Groups

### Steering

- `STEER_GAIN` controls the base steering response to the car angle.
- `CENTERING_GAIN` pulls the car back toward the track center. Lower values allow
  wider racing lines but increase the risk of leaving the track.
- `STEER_D_GAIN` dampens steering changes between steps.
- `APEX_SHIFT_GAIN` moves the target line toward the inside of a corner.
- `APEX_SCALE` smooths the apex shift. Very low values behave close to a
  bang-bang controller; larger values reduce oscillation but can slow the car.

### Speed And Vision

- `VISION_LONG_STRAIGHT`, `VISION_FAST_CORNER`, and `VISION_MED_CORNER` classify
  the visible path ahead.
- `TARGET_STRAIGHT_SPEED`, `SPEED_FAST_CORNER`, `SPEED_MED_CORNER`,
  `MIN_NORMAL_CORNER_SPEED`, and `SAFE_SHARP_CORNER_SPEED` define the target
  speed for each detected track situation.
- The intended ordering is `VISION_MED_CORNER < VISION_FAST_CORNER <
  VISION_LONG_STRAIGHT`. Invalid Optuna suggestions are pruned.

### Braking And Traction

- `BRAKE_THRESHOLD` decides when the car is too fast for the current target.
- `BRAKE_DISTANCE_LIN` and `BRAKE_DISTANCE_QUAD` estimate a safe braking
  distance from current speed.
- `TRAIL_BRAKE_DIVISOR` keeps braking active deeper into corner entry when the
  exit is still far away.
- `BRAKE_PRESS_DIVISOR` controls how aggressively the brake is applied.
- `ABS_SLIP_THRESHOLD`, `ABS_MODULATION`, and `ABS_D_GAIN` reduce wheel lockup.
- `TCS_SLIP_THRESHOLD` reduces throttle when wheel slip becomes too high.

## Optuna Modes

`optimize.py` selects a tuning mode from environment variables:

| Environment variable | Study name | Notes |
| --- | --- | --- |
| `SMOKE=1` | `smoke_v1` | Short sanity run. |
| default | `car1ow1_v1` | Full search over the initial parameter set. |
| `EXTENDED=1` | `car1ow1_v2` | Wider limits for saturated parameters. |
| `BRAKES=1` | `car1ow1_v3_brakes` | Brake-only tuning from the extended baseline. |
| `BRAKES_EXT=1` | `car1ow1_v3b_brakes_ext` | Wider brake limits. |
| `VISION=1` | `car1ow1_v4_vision` | Vision and speed threshold tuning. |
| `JOINT=1` | `car1ow1_v5_joint` | Joint fit around `vision_best.json`. |
| `ANTISLALOM=1` | `car1ow1_v6_antislalom` | Apex smoothing experiment. |
| `JOINT64=1` | `car1ow1_v7_joint64` | Joint fit with lower simulator speedup. |
| `ABS=1` | `car1ow1_v8_abs` | ABS, TCS, and steering derivative tuning. |
| `JOINT_ABS=1` | `car1ow1_v9_joint_abs` | Joint optimization with ABS-related parameters. |

Examples:

```powershell
$env:SMOKE = "1"
python optimize.py

$env:VISION = "1"
python optimize.py
```

## Working Notes

- Treat `params/best/vision_best.json` as the validated baseline.
- Before a new long tuning phase, copy the active `params.json` into
  `params/snapshots/`.
- After tuning, keep the best result in `params/best/<mode>_best.json`.
- Validate important tuning results with `python startup.py` at normal simulator
  speed, because very high simulation speed can overfit to physics timing.
- Failed experiments are kept when they explain a useful tuning boundary or
  regression.
