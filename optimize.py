import optuna
import os
import time
import json
import subprocess
import sys
import pyautogui

FIRST_RUN = True

# ============== OPTIMIZATION MODE ==============
# SMOKE=1     -> 20 trials, +/-20% around params_baseline (Phase 2 from PLAN.md)
# EXTENDED=1  -> extended limits for saturated parameters from Phase 3 (Phase 5)
# BRAKES=1    -> 7 old params frozen from params_extended_best.json,
#                tuning only 4 new braking params (Phase 6a)
# BRAKES_EXT=1-> like BRAKES, but extended LOWER limits for brake-bounds (Phase 6b-rev),
#                because 3/4 params in 6a hit the floor; center is params_brakes_best.json
# VISION=1    -> 11 frozen from 6b-rev, tuning 5 vision/speed thresholds (Phase 6b-vision)
# JOINT=1     -> Phase 6c: ALL 16 params together, narrow ±10% around params_vision_best,
#                + 2 SATURATED extended (SPEED_FAST_CORNER ceiling 270, VISION_MED_CORNER floor 45).
# ANTISLALOM=1-> Phase 7: after refactor calculate_steering (smooth tanh apex). Frozen 14 from params_vision_best,
#                tuning APEX_SHIFT_GAIN (extended range) + new APEX_SCALE.
#                JOINT 6c was an overfit to speed=128x (5/5 DNF at 1x), so we rollback to baseline 6b-vision.
# JOINT64=1   -> Phase 8: like JOINT (16 params ±10% around vision_best), but with SPEEDUP_PRESSES=6
#                (fewer Numpad+ presses) to eliminate the 128x vs 1x physics gap. Validatable results at the cost of time.
#                Overnight run on a secondary machine (~6-10h for 250 trials).
# ABS=1       -> Phase 9: Optimization of ABS PID, TCS, and steering PD controller.
# JOINT_ABS=1 -> Phase 10: Joint optimization of all 21 parameters (16 old + 5 from ABS) based on abs_best.json.
# default     -> full search-space (Phase 3)
SMOKE = os.environ.get("SMOKE", "0") == "1"
EXTENDED = os.environ.get("EXTENDED", "0") == "1"
BRAKES = os.environ.get("BRAKES", "0") == "1"
BRAKES_EXT = os.environ.get("BRAKES_EXT", "0") == "1"
VISION = os.environ.get("VISION", "0") == "1"
JOINT = os.environ.get("JOINT", "0") == "1"
ANTISLALOM = os.environ.get("ANTISLALOM", "0") == "1"
JOINT64 = os.environ.get("JOINT64", "0") == "1"
ABS = os.environ.get("ABS", "0") == "1"
JOINT_ABS = os.environ.get("JOINT_ABS", "0") == "1"
if JOINT_ABS:
    MODE = "JOINT_ABS"
elif JOINT64:
    MODE = "JOINT64"
elif ABS:
    MODE = "ABS"
elif ANTISLALOM:
    MODE = "ANTISLALOM"
elif JOINT:
    MODE = "JOINT"
elif VISION:
    MODE = "VISION"
elif BRAKES_EXT:
    MODE = "BRAKES_EXT"
elif BRAKES:
    MODE = "BRAKES"
elif EXTENDED:
    MODE = "EXTENDED"
elif SMOKE:
    MODE = "SMOKE"
else:
    MODE = "FULL"
DEFAULT_STUDY = {
    "SMOKE": "smoke_v1",
    "FULL": "car1ow1_v1",
    "EXTENDED": "car1ow1_v2",
    "BRAKES": "car1ow1_v3_brakes",
    "BRAKES_EXT": "car1ow1_v3b_brakes_ext",
    "VISION": "car1ow1_v4_vision",
    "JOINT": "car1ow1_v5_joint",
    "ANTISLALOM": "car1ow1_v6_antislalom",
    "JOINT64": "car1ow1_v7_joint64",
    "ABS": "car1ow1_v8_abs",
    "JOINT_ABS": "car1ow1_v9_joint_abs"
}[MODE]
DEFAULT_TRIALS = {"SMOKE": "20", "FULL": "500", "EXTENDED": "500", "BRAKES": "200", "BRAKES_EXT": "200", "VISION": "200", "JOINT": "200", "ANTISLALOM": "100", "JOINT64": "250", "ABS": "200", "JOINT_ABS": "250"}[MODE]
# Phase 8: configurable number of Numpad+ presses for sim speedup.
# 8 presses = 128x (default, current std), 6 presses = ~32x (less overfit, much slower).
# JOINT64 forces 6 if env var is not set.
DEFAULT_SPEEDUP = "6" if MODE == "JOINT64" else "8"
SPEEDUP_PRESSES = int(os.environ.get("SPEEDUP_PRESSES", DEFAULT_SPEEDUP))
N_TRIALS = int(os.environ.get("N_TRIALS", DEFAULT_TRIALS))
STUDY_NAME = os.environ.get("STUDY_NAME", DEFAULT_STUDY)
STORAGE_URL = "sqlite:///optuna_corkscrew.db"

# Phase 6a/6b-rev/6b-vision: frozen params from previous phases
FROZEN_PARAMS = {}
if MODE in ("BRAKES", "BRAKES_EXT"):
    # 7 old from Phase 5, tuning 4 brake-params
    default_frozen = "params/best/extended_best.json"
elif MODE == "VISION":
    # 7 old + 4 brake-params from 6b-rev (11 total), tuning 5 vision-params
    default_frozen = "params/best/brakes_ext_best.json"
elif MODE == "JOINT":
    # Phase 6c: center of search-space is all 16 params from vision_best.
    # FROZEN_PARAMS is only used as a "center" (reading values to calculate bounds),
    # but no param is frozen here - all are tuned simultaneously.
    default_frozen = "params/best/vision_best.json"
elif MODE == "JOINT64":
    # Phase 8: identical logic as JOINT, but at 6 presses (~32x) to validate results.
    default_frozen = "params/best/vision_best.json"
elif MODE == "ANTISLALOM":
    # Phase 7: 14 frozen from vision_best (rollback after JOINT 6c overfit),
    # tuning APEX_SHIFT_GAIN + new APEX_SCALE (smooth tanh apex in my_racer.py).
    default_frozen = "params/best/vision_best.json"
elif MODE == "ABS":
    # Phase 9: Starting with vision_best (baseline) and tuning PIDs and traction
    default_frozen = "params/best/vision_best.json"
elif MODE == "JOINT_ABS":
    # Phase 10: Taking the complete set of 21 best parameters and searching for joint synergies
    default_frozen = "params/best/joint_abs.json"
else:
    default_frozen = None
if default_frozen is not None:
    frozen_path = os.environ.get("FROZEN_PARAMS_PATH", default_frozen)
    if not os.path.exists(frozen_path):
        raise FileNotFoundError(
            f"{MODE}=1 requires {frozen_path}. "
            "Or set FROZEN_PARAMS_PATH to another file."
        )
    with open(frozen_path, "r") as f:
        FROZEN_PARAMS = json.load(f)
    print(f"[Optuna] {MODE} mode: frozen {len(FROZEN_PARAMS)} params from {frozen_path}: {FROZEN_PARAMS}")
# =================================================

def run_torcs(params):
    global FIRST_RUN
    # Passing genes (parameters) to the bot
    with open("params.json", "w") as f:
        json.dump(params, f)
        
    os.system('taskkill /f /im wtorcs.exe >nul 2>&1')
    time.sleep(0.5)
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    torcs_dir = os.path.join(script_dir, "torcs")
    cwd = os.getcwd()
    
    if os.path.exists(torcs_dir):
        os.chdir(torcs_dir)
        
    os.system('start "" wtorcs.exe -nofuel -nodamage -nolaptime')
    
    # Extended time for loading the game into RAM on first run
    if FIRST_RUN:
        time.sleep(8.0)
        FIRST_RUN = False
    else:
        time.sleep(5.0)
    
    # Quick navigation to "Quick Race" menu
    for key in ['enter', 'enter', 'enter', 'enter']:
        pyautogui.press(key)
        time.sleep(0.2)
        
    time.sleep(1.0)
    os.chdir(cwd)
    
    # Simulated Numpad '+' (add) keyboard -> sim speedup. SPEEDUP_PRESSES controls:
    # 8 presses = 128x (FULL/EXTENDED/.../JOINT/ANTISLALOM), 6 presses = ~32x (JOINT64, less overfit).
    for _ in range(SPEEDUP_PRESSES):
        pyautogui.press('add')
        time.sleep(0.1)
    
    print(f"Optuna race is running! Waiting for result...")
    subprocess.run([sys.executable, "my_racer.py"])
    
    os.system('taskkill /f /im wtorcs.exe >nul 2>&1')
    time.sleep(0.5)
    
    # Receive result from bot
    try:
        with open("last_lap.json", "r") as f:
            res = json.load(f)
            lap_time = res.get("lap_time", 9999.9)
            dist = res.get("dist_raced", 0)
    except Exception:
        lap_time = 9999.9
        dist = 0
        
    # If bot crashes (DNF), penalize less for genes that drove further!
    if lap_time >= 9999.0:
        return 10000.0 - dist
        
    return lap_time

def objective(trial):
    if MODE == "SMOKE":
        # +/-20% around params_baseline.json (defaults achieve 1:37.47 on Corkscrew)
        params = {
            "TARGET_STRAIGHT_SPEED": trial.suggest_float("TARGET_STRAIGHT_SPEED", 260.0, 310.0),
            "SAFE_SHARP_CORNER_SPEED": trial.suggest_float("SAFE_SHARP_CORNER_SPEED", 50.0, 72.0),
            "MIN_NORMAL_CORNER_SPEED": trial.suggest_float("MIN_NORMAL_CORNER_SPEED", 95.0, 130.0),
            "STEER_GAIN": trial.suggest_float("STEER_GAIN", 24.0, 36.0),
            "CENTERING_GAIN": trial.suggest_float("CENTERING_GAIN", 0.16, 0.24),
            "BRAKE_THRESHOLD": trial.suggest_float("BRAKE_THRESHOLD", 0.24, 0.36),
            "APEX_SHIFT_GAIN": trial.suggest_float("APEX_SHIFT_GAIN", 0.37, 0.55),
        }
    elif MODE == "EXTENDED":
        # Extended limits for saturated parameters from Phase 3:
        # STEER_GAIN floor 15->5, CENTERING_GAIN floor 0.05->0.0,
        # MIN_NORMAL_CORNER_SPEED ceiling 150->180, SAFE_SHARP_CORNER_SPEED floor 50->40
        params = {
            "TARGET_STRAIGHT_SPEED": trial.suggest_float("TARGET_STRAIGHT_SPEED", 240.0, 310.0),
            "SAFE_SHARP_CORNER_SPEED": trial.suggest_float("SAFE_SHARP_CORNER_SPEED", 40.0, 95.0),
            "MIN_NORMAL_CORNER_SPEED": trial.suggest_float("MIN_NORMAL_CORNER_SPEED", 90.0, 180.0),
            "STEER_GAIN": trial.suggest_float("STEER_GAIN", 5.0, 45.0),
            "CENTERING_GAIN": trial.suggest_float("CENTERING_GAIN", 0.0, 0.4),
            "BRAKE_THRESHOLD": trial.suggest_float("BRAKE_THRESHOLD", 0.1, 0.5),
            "APEX_SHIFT_GAIN": trial.suggest_float("APEX_SHIFT_GAIN", 0.1, 0.8),
        }
    elif MODE == "BRAKES":
        # Phase 6a: 7 old params frozen from params_extended_best.json,
        # tuning only 4 new braking params.
        params = dict(FROZEN_PARAMS)
        params["BRAKE_DISTANCE_LIN"]  = trial.suggest_float("BRAKE_DISTANCE_LIN",  0.20, 0.55)
        params["BRAKE_DISTANCE_QUAD"] = trial.suggest_float("BRAKE_DISTANCE_QUAD", 800.0, 2000.0)
        params["TRAIL_BRAKE_DIVISOR"] = trial.suggest_float("TRAIL_BRAKE_DIVISOR", 20.0, 80.0)
        params["BRAKE_PRESS_DIVISOR"] = trial.suggest_float("BRAKE_PRESS_DIVISOR", 25.0, 80.0)
    elif MODE == "BRAKES_EXT":
        # Phase 6b-rev: 7 old frozen, brake-bounds extended LOWER because 3/4 hit the floor in 6a.
        # TRAIL_BRAKE_DIVISOR narrowed (40 was sweet spot, no sense searching beyond 80).
        params = dict(FROZEN_PARAMS)
        params["BRAKE_DISTANCE_LIN"]  = trial.suggest_float("BRAKE_DISTANCE_LIN",  0.10, 0.30)
        params["BRAKE_DISTANCE_QUAD"] = trial.suggest_float("BRAKE_DISTANCE_QUAD", 500.0, 1200.0)
        params["TRAIL_BRAKE_DIVISOR"] = trial.suggest_float("TRAIL_BRAKE_DIVISOR", 25.0, 60.0)
        params["BRAKE_PRESS_DIVISOR"] = trial.suggest_float("BRAKE_PRESS_DIVISOR", 15.0, 45.0)
    elif MODE == "VISION":
        # Phase 6b-vision: 11 frozen (7 old + 4 brake-params from 6b-rev),
        # tuning 5 vision/speed thresholds. Ordering constraint in if/elif:
        # VISION_MED < VISION_FAST < VISION_LONG (otherwise elifs eat each other).
        # Suggest_float independently + invalid if violated -> TPE will learn.
        params = dict(FROZEN_PARAMS)
        v_long = trial.suggest_float("VISION_LONG_STRAIGHT", 100.0, 160.0)
        v_fast = trial.suggest_float("VISION_FAST_CORNER",   70.0, 110.0)
        v_med  = trial.suggest_float("VISION_MED_CORNER",    45.0,  80.0)
        if not (v_med < v_fast < v_long):
            # Invalid combination - report as prune so TPE avoids it
            raise optuna.TrialPruned()
        params["VISION_LONG_STRAIGHT"] = v_long
        params["VISION_FAST_CORNER"]   = v_fast
        params["VISION_MED_CORNER"]    = v_med
        params["SPEED_FAST_CORNER"]    = trial.suggest_float("SPEED_FAST_CORNER", 200.0, 270.0)
        params["SPEED_MED_CORNER"]     = trial.suggest_float("SPEED_MED_CORNER", 150.0, 230.0)
    elif MODE == "JOINT":
        # Phase 6c: joint refit, all 16 params in narrow ±10% around params_vision_best,
        # EXCEPTIONS - 2 saturations from 6b-vision extended:
        #   SPEED_FAST_CORNER: 269.7 hit ceiling 270 -> extended to 250-310
        #   VISION_MED_CORNER: 46.2 hit floor 45 -> extended floor to 25
        # Center (FROZEN_PARAMS) read from params_vision_best.json.
        # Vision ordering constraint: VISION_MED < VISION_FAST < VISION_LONG (like in VISION).
        c = FROZEN_PARAMS  # center, alias for brevity
        params = {}
        params["TARGET_STRAIGHT_SPEED"]   = trial.suggest_float("TARGET_STRAIGHT_SPEED",   c["TARGET_STRAIGHT_SPEED"]   * 0.90, c["TARGET_STRAIGHT_SPEED"]   * 1.10)
        params["SAFE_SHARP_CORNER_SPEED"] = trial.suggest_float("SAFE_SHARP_CORNER_SPEED", c["SAFE_SHARP_CORNER_SPEED"] * 0.90, c["SAFE_SHARP_CORNER_SPEED"] * 1.10)
        params["MIN_NORMAL_CORNER_SPEED"] = trial.suggest_float("MIN_NORMAL_CORNER_SPEED", c["MIN_NORMAL_CORNER_SPEED"] * 0.90, c["MIN_NORMAL_CORNER_SPEED"] * 1.10)
        params["STEER_GAIN"]              = trial.suggest_float("STEER_GAIN",              c["STEER_GAIN"]              * 0.90, c["STEER_GAIN"]              * 1.10)
        params["CENTERING_GAIN"]          = trial.suggest_float("CENTERING_GAIN",          c["CENTERING_GAIN"]          * 0.90, c["CENTERING_GAIN"]          * 1.10)
        params["BRAKE_THRESHOLD"]         = trial.suggest_float("BRAKE_THRESHOLD",         c["BRAKE_THRESHOLD"]         * 0.90, c["BRAKE_THRESHOLD"]         * 1.10)
        params["APEX_SHIFT_GAIN"]         = trial.suggest_float("APEX_SHIFT_GAIN",         c["APEX_SHIFT_GAIN"]         * 0.90, c["APEX_SHIFT_GAIN"]         * 1.10)
        params["BRAKE_DISTANCE_LIN"]      = trial.suggest_float("BRAKE_DISTANCE_LIN",      c["BRAKE_DISTANCE_LIN"]      * 0.90, c["BRAKE_DISTANCE_LIN"]      * 1.10)
        params["BRAKE_DISTANCE_QUAD"]     = trial.suggest_float("BRAKE_DISTANCE_QUAD",     c["BRAKE_DISTANCE_QUAD"]     * 0.90, c["BRAKE_DISTANCE_QUAD"]     * 1.10)
        params["TRAIL_BRAKE_DIVISOR"]     = trial.suggest_float("TRAIL_BRAKE_DIVISOR",     c["TRAIL_BRAKE_DIVISOR"]     * 0.90, c["TRAIL_BRAKE_DIVISOR"]     * 1.10)
        params["BRAKE_PRESS_DIVISOR"]     = trial.suggest_float("BRAKE_PRESS_DIVISOR",     c["BRAKE_PRESS_DIVISOR"]     * 0.90, c["BRAKE_PRESS_DIVISOR"]     * 1.10)
        params["VISION_LONG_STRAIGHT"]    = trial.suggest_float("VISION_LONG_STRAIGHT",    c["VISION_LONG_STRAIGHT"]    * 0.90, c["VISION_LONG_STRAIGHT"]    * 1.10)
        params["VISION_FAST_CORNER"]      = trial.suggest_float("VISION_FAST_CORNER",      c["VISION_FAST_CORNER"]      * 0.90, c["VISION_FAST_CORNER"]      * 1.10)
        params["SPEED_MED_CORNER"]        = trial.suggest_float("SPEED_MED_CORNER",        c["SPEED_MED_CORNER"]        * 0.90, c["SPEED_MED_CORNER"]        * 1.10)
        # 2 saturated -> extended bounds (not ±10%)
        params["SPEED_FAST_CORNER"]       = trial.suggest_float("SPEED_FAST_CORNER",       250.0, 310.0)
        params["VISION_MED_CORNER"]       = trial.suggest_float("VISION_MED_CORNER",        25.0,  60.0)
        # Threshold order constraint (like in VISION mode)
        if not (params["VISION_MED_CORNER"] < params["VISION_FAST_CORNER"] < params["VISION_LONG_STRAIGHT"]):
            raise optuna.TrialPruned()
    elif MODE == "JOINT64":
        # Phase 8: identical search-space as JOINT (±10% around vision_best, 2 saturated extended),
        # but executed with SPEEDUP_PRESSES=6 (~32x) instead of 8 (~128x).
        # Goal: results should be validatable at 1x (eliminating overfit from JOINT 6c).
        c = FROZEN_PARAMS
        params = {}
        params["TARGET_STRAIGHT_SPEED"]   = trial.suggest_float("TARGET_STRAIGHT_SPEED",   c["TARGET_STRAIGHT_SPEED"]   * 0.90, c["TARGET_STRAIGHT_SPEED"]   * 1.10)
        params["SAFE_SHARP_CORNER_SPEED"] = trial.suggest_float("SAFE_SHARP_CORNER_SPEED", c["SAFE_SHARP_CORNER_SPEED"] * 0.90, c["SAFE_SHARP_CORNER_SPEED"] * 1.10)
        params["MIN_NORMAL_CORNER_SPEED"] = trial.suggest_float("MIN_NORMAL_CORNER_SPEED", c["MIN_NORMAL_CORNER_SPEED"] * 0.90, c["MIN_NORMAL_CORNER_SPEED"] * 1.10)
        params["STEER_GAIN"]              = trial.suggest_float("STEER_GAIN",              c["STEER_GAIN"]              * 0.90, c["STEER_GAIN"]              * 1.10)
        params["CENTERING_GAIN"]          = trial.suggest_float("CENTERING_GAIN",          c["CENTERING_GAIN"]          * 0.90, c["CENTERING_GAIN"]          * 1.10)
        params["BRAKE_THRESHOLD"]         = trial.suggest_float("BRAKE_THRESHOLD",         c["BRAKE_THRESHOLD"]         * 0.90, c["BRAKE_THRESHOLD"]         * 1.10)
        params["APEX_SHIFT_GAIN"]         = trial.suggest_float("APEX_SHIFT_GAIN",         c["APEX_SHIFT_GAIN"]         * 0.90, c["APEX_SHIFT_GAIN"]         * 1.10)
        params["BRAKE_DISTANCE_LIN"]      = trial.suggest_float("BRAKE_DISTANCE_LIN",      c["BRAKE_DISTANCE_LIN"]      * 0.90, c["BRAKE_DISTANCE_LIN"]      * 1.10)
        params["BRAKE_DISTANCE_QUAD"]     = trial.suggest_float("BRAKE_DISTANCE_QUAD",     c["BRAKE_DISTANCE_QUAD"]     * 0.90, c["BRAKE_DISTANCE_QUAD"]     * 1.10)
        params["TRAIL_BRAKE_DIVISOR"]     = trial.suggest_float("TRAIL_BRAKE_DIVISOR",     c["TRAIL_BRAKE_DIVISOR"]     * 0.90, c["TRAIL_BRAKE_DIVISOR"]     * 1.10)
        params["BRAKE_PRESS_DIVISOR"]     = trial.suggest_float("BRAKE_PRESS_DIVISOR",     c["BRAKE_PRESS_DIVISOR"]     * 0.90, c["BRAKE_PRESS_DIVISOR"]     * 1.10)
        params["VISION_LONG_STRAIGHT"]    = trial.suggest_float("VISION_LONG_STRAIGHT",    c["VISION_LONG_STRAIGHT"]    * 0.90, c["VISION_LONG_STRAIGHT"]    * 1.10)
        params["VISION_FAST_CORNER"]      = trial.suggest_float("VISION_FAST_CORNER",      c["VISION_FAST_CORNER"]      * 0.90, c["VISION_FAST_CORNER"]      * 1.10)
        params["SPEED_MED_CORNER"]        = trial.suggest_float("SPEED_MED_CORNER",        c["SPEED_MED_CORNER"]        * 0.90, c["SPEED_MED_CORNER"]        * 1.10)
        params["SPEED_FAST_CORNER"]       = trial.suggest_float("SPEED_FAST_CORNER",       250.0, 310.0)
        params["VISION_MED_CORNER"]       = trial.suggest_float("VISION_MED_CORNER",        25.0,  60.0)
        if not (params["VISION_MED_CORNER"] < params["VISION_FAST_CORNER"] < params["VISION_LONG_STRAIGHT"]):
            raise optuna.TrialPruned()
    elif MODE == "ANTISLALOM":
        # Phase 7: refactor calculate_steering -> smooth tanh apex (anti-slalom).
        # 14 params frozen from params_vision_best.json (baseline 6b-vision, ~85.99-86.05s).
        # Tuning:
        #   APEX_SHIFT_GAIN: wide range because smooth tanh has different sensitivity than bang-bang
        #   APEX_SCALE: new param, controls how fast tanh saturates (smaller = sharper)
        params = dict(FROZEN_PARAMS)
        params["APEX_SHIFT_GAIN"] = trial.suggest_float("APEX_SHIFT_GAIN", 0.10, 0.80)
        # APEX_SCALE: wide range - small values (~0.05) ~= bang-bang (vision_best baseline),
        # large values (>1.0) strongly dampen slalom oscillations in mid-corner.
        # Sanity check at 0.3 gave 3/5 DNF + 5s slowdown - so sweet spot is either 0.05 or 1.0+.
        params["APEX_SCALE"]      = trial.suggest_float("APEX_SCALE",      0.05, 5.00)
    elif MODE == "ABS":
        # Optimization of added PD/PID controllers and TCS
        params = dict(FROZEN_PARAMS)
        params["ABS_SLIP_THRESHOLD"] = trial.suggest_float("ABS_SLIP_THRESHOLD", 1.0, 6.0)
        params["ABS_MODULATION"]     = trial.suggest_float("ABS_MODULATION", 0.1, 0.8)
        params["ABS_D_GAIN"]         = trial.suggest_float("ABS_D_GAIN", 0.0, 0.5)
        params["TCS_SLIP_THRESHOLD"] = trial.suggest_float("TCS_SLIP_THRESHOLD", 2.0, 10.0)
        params["STEER_D_GAIN"]       = trial.suggest_float("STEER_D_GAIN", 0.0, 5.0)
    elif MODE == "JOINT_ABS":
        # Phase 10: All 21 parameters simultaneously around the best run (abs_best.json)
        c = FROZEN_PARAMS
        params = {}
        # Forcing higher limits for maximum speed, so Optuna searches for V-MAX again
        params["TARGET_STRAIGHT_SPEED"]   = trial.suggest_float("TARGET_STRAIGHT_SPEED",   max(290.0, c["TARGET_STRAIGHT_SPEED"] * 0.95), 320.0)
        params["SAFE_SHARP_CORNER_SPEED"] = trial.suggest_float("SAFE_SHARP_CORNER_SPEED", 70.0, 85.0)
        params["MIN_NORMAL_CORNER_SPEED"] = trial.suggest_float("MIN_NORMAL_CORNER_SPEED", 80.0, 95.0)
        params["STEER_GAIN"]              = trial.suggest_float("STEER_GAIN",              c["STEER_GAIN"]              * 0.90, c["STEER_GAIN"]              * 1.10)
        params["CENTERING_GAIN"]          = trial.suggest_float("CENTERING_GAIN",          c["CENTERING_GAIN"]          * 0.80, c["CENTERING_GAIN"]          * 1.20)
        params["BRAKE_THRESHOLD"]         = trial.suggest_float("BRAKE_THRESHOLD",         c["BRAKE_THRESHOLD"]         * 0.90, c["BRAKE_THRESHOLD"]         * 1.10)
        params["APEX_SHIFT_GAIN"]         = trial.suggest_float("APEX_SHIFT_GAIN",         c["APEX_SHIFT_GAIN"]         * 0.90, c["APEX_SHIFT_GAIN"]         * 1.10)
        params["BRAKE_DISTANCE_LIN"]      = trial.suggest_float("BRAKE_DISTANCE_LIN",      c["BRAKE_DISTANCE_LIN"]      * 0.80, c["BRAKE_DISTANCE_LIN"]      * 1.30) # Increased upper limit to allow longer braking
        params["BRAKE_DISTANCE_QUAD"]     = trial.suggest_float("BRAKE_DISTANCE_QUAD",     c["BRAKE_DISTANCE_QUAD"]     * 0.60, c["BRAKE_DISTANCE_QUAD"]     * 1.10) # REDUCED QUAD limit allows significantly LARGER braking distance (division)
        params["TRAIL_BRAKE_DIVISOR"]     = trial.suggest_float("TRAIL_BRAKE_DIVISOR",     c["TRAIL_BRAKE_DIVISOR"]     * 0.90, c["TRAIL_BRAKE_DIVISOR"]     * 1.10)
        params["BRAKE_PRESS_DIVISOR"]     = trial.suggest_float("BRAKE_PRESS_DIVISOR",     c["BRAKE_PRESS_DIVISOR"]     * 0.90, c["BRAKE_PRESS_DIVISOR"]     * 1.10)
        params["VISION_LONG_STRAIGHT"]    = trial.suggest_float("VISION_LONG_STRAIGHT",    c["VISION_LONG_STRAIGHT"]    * 0.90, c["VISION_LONG_STRAIGHT"]    * 1.10)
        params["VISION_FAST_CORNER"]      = trial.suggest_float("VISION_FAST_CORNER",      c["VISION_FAST_CORNER"]      * 0.90, c["VISION_FAST_CORNER"]      * 1.10)
        params["SPEED_MED_CORNER"]        = trial.suggest_float("SPEED_MED_CORNER",        c["SPEED_MED_CORNER"]        * 0.90, c["SPEED_MED_CORNER"]        * 1.10)
        params["SPEED_FAST_CORNER"]       = trial.suggest_float("SPEED_FAST_CORNER",       c["SPEED_FAST_CORNER"]       * 0.95, c["SPEED_FAST_CORNER"]       * 1.05)
        params["VISION_MED_CORNER"]       = trial.suggest_float("VISION_MED_CORNER",       c["VISION_MED_CORNER"]       * 0.90, c["VISION_MED_CORNER"]       * 1.10)
        # ABS + TCS
        params["ABS_SLIP_THRESHOLD"]      = trial.suggest_float("ABS_SLIP_THRESHOLD",      c["ABS_SLIP_THRESHOLD"]      * 0.80, c["ABS_SLIP_THRESHOLD"]      * 1.20)
        params["ABS_MODULATION"]          = trial.suggest_float("ABS_MODULATION",          c["ABS_MODULATION"]          * 0.80, c["ABS_MODULATION"]          * 1.20)
        params["ABS_D_GAIN"]              = trial.suggest_float("ABS_D_GAIN",              max(0.0, c["ABS_D_GAIN"] - 0.05), c["ABS_D_GAIN"] + 0.10)
        params["TCS_SLIP_THRESHOLD"]      = trial.suggest_float("TCS_SLIP_THRESHOLD",      c["TCS_SLIP_THRESHOLD"]      * 0.80, c["TCS_SLIP_THRESHOLD"]      * 1.20)
        params["STEER_D_GAIN"]            = trial.suggest_float("STEER_D_GAIN",            0.0, 1.5) # Limiting high jerks
        if not (params["VISION_MED_CORNER"] < params["VISION_FAST_CORNER"] < params["VISION_LONG_STRAIGHT"]):
            raise optuna.TrialPruned()
    else:  # FULL
        params = {
            "TARGET_STRAIGHT_SPEED": trial.suggest_float("TARGET_STRAIGHT_SPEED", 240.0, 310.0),
            "SAFE_SHARP_CORNER_SPEED": trial.suggest_float("SAFE_SHARP_CORNER_SPEED", 50.0, 95.0),
            "MIN_NORMAL_CORNER_SPEED": trial.suggest_float("MIN_NORMAL_CORNER_SPEED", 90.0, 150.0),
            "STEER_GAIN": trial.suggest_float("STEER_GAIN", 15.0, 45.0),
            "CENTERING_GAIN": trial.suggest_float("CENTERING_GAIN", 0.05, 0.4),
            "BRAKE_THRESHOLD": trial.suggest_float("BRAKE_THRESHOLD", 0.1, 0.5),
            "APEX_SHIFT_GAIN": trial.suggest_float("APEX_SHIFT_GAIN", 0.1, 0.8),
        }
    return run_torcs(params)

if __name__ == "__main__":
    print(f"[Optuna] mode={MODE}, n_trials={N_TRIALS}, study={STUDY_NAME}, speedup_presses={SPEEDUP_PRESSES}")
    print(f"[Optuna] storage={STORAGE_URL} (Ctrl+C is safe, restarting will resume study)")

    study = optuna.create_study(
        direction="minimize",
        storage=STORAGE_URL,
        study_name=STUDY_NAME,
        load_if_exists=True,
    )

    completed_before = len([t for t in study.trials if t.state.name == "COMPLETE"])
    print(f"[Optuna] already completed trials in DB: {completed_before}")

    try:
        study.optimize(objective, n_trials=N_TRIALS)
    except KeyboardInterrupt:
        print("\n[!] Optimization interrupted by user (Ctrl+C).")

    print("\n================== COMPLETED ==================")
    completed = [t for t in study.trials if t.state.name == "COMPLETE"]
    # DNF: obj returns 10000 - dist_raced (typically 6000-9000); lap_time typically 80-150 s
    dnf_count = sum(1 for t in completed if t.value is not None and t.value > 200.0)
    lap_count = len(completed) - dnf_count
    print(f"Completed trials: {len(completed)} / {len(study.trials)}, lap={lap_count}, DNF={dnf_count}")
    if lap_count > 0:
        lap_vals = sorted(t.value for t in completed if t.value is not None and t.value <= 200.0)
        print(f"Lap time stats: min={lap_vals[0]:.3f}, mean={sum(lap_vals)/len(lap_vals):.3f}, max={lap_vals[-1]:.3f}")

    try:
        print(f"Best params: {study.best_params}")
        print(f"Best lap_time: {study.best_value:.3f} s")
        # In BRAKES mode (and future frozen-modes) study.best_params contains only
        # parameters suggested by trial.suggest_*. We must merge FROZEN_PARAMS
        # so my_racer.py has a COMPLETE 7+N set (and not defaults instead of the old 7).
        full_params = {**FROZEN_PARAMS, **study.best_params}
        with open("params.json", "w") as f:
            json.dump(full_params, f, indent=4)
        if FROZEN_PARAMS:
            print(f"Saved params.json (merge: {len(FROZEN_PARAMS)} frozen + {len(study.best_params)} tuned).")
        else:
            print("Saved params.json.")
    except ValueError:
        print("No data - no race was fully completed.")
