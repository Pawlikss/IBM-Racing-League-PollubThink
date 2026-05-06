import optuna
import os
import time
import json
import subprocess
import sys
import pyautogui

FIRST_RUN = True

# ============== TRYB OPTYMALIZACJI ==============
# SMOKE=1     -> 20 prob, +/-20% wokol params_baseline (Faza 2 z PLAN.md)
# EXTENDED=1  -> rozszerzone granice na nasycone parametry z Fazy 3 (Faza 5)
# BRAKES=1    -> 7 starych params zafrozonych z params_extended_best.json,
#                tunowanie tylko 4 nowych params hamowania (Faza 6a)
# BRAKES_EXT=1-> jak BRAKES, ale rozszerzone DOLNE granice brake-bounds (Faza 6b-rev),
#                bo 3/4 params w 6a uderzyly w floor; centrum to params_brakes_best.json
# VISION=1    -> 11 zafrozonych z 6b-rev, tunujemy 5 progow vision/speed (Faza 6b-vision)
# JOINT=1     -> Faza 6c: WSZYSTKIE 16 params razem, waskie ±10% wokol params_vision_best,
#                + 2 NASYCONE rozszerzone (SPEED_FAST_CORNER ceiling 270, VISION_MED_CORNER floor 45).
# ANTISLALOM=1-> Faza 7: po refactor calculate_steering (smooth tanh apex). Zafrozone 14 z params_vision_best,
#                tunujemy APEX_SHIFT_GAIN (rozszerzony zakres) + nowy APEX_SCALE.
#                JOINT 6c byl overfitem do speed=128x (5/5 DNF przy 1x), wiec wracamy do baseline 6b-vision.
# JOINT64=1   -> Faza 8: jak JOINT (16 params ±10% wokol vision_best), ale przy SPEEDUP_PRESSES=6
#                (mniej presses Numpad+) zeby wyeliminowac gap fizyki 128x vs 1x. Walidowalne wyniki kosztem czasu.
#                Overnight run na drugim komputerze (~6-10h dla 250 trials).
# ABS=1       -> Faza 9: Optymalizacja ABS PID, TCS i kontrolera PD kierownicy.
# JOINT_ABS=1 -> Faza 10: Wspolna optymalizacja wszystkich 21 parametrów (16 starych + 5 z ABS) na bazie abs_best.json.
# default     -> pelny search-space (Faza 3)
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
# Faza 8: konfigurowalna liczba Numpad+ presses dla sim speedup.
# 8 presses = 128x (default, dotychczasowy std), 6 presses = ~32x (mniej overfit, znacznie wolniej).
# JOINT64 forsuje 6 jezeli env var nie ustawiony.
DEFAULT_SPEEDUP = "6" if MODE == "JOINT64" else "8"
SPEEDUP_PRESSES = int(os.environ.get("SPEEDUP_PRESSES", DEFAULT_SPEEDUP))
N_TRIALS = int(os.environ.get("N_TRIALS", DEFAULT_TRIALS))
STUDY_NAME = os.environ.get("STUDY_NAME", DEFAULT_STUDY)
STORAGE_URL = "sqlite:///optuna_corkscrew.db"

# Faza 6a/6b-rev/6b-vision: zafrozone params z poprzednich faz
FROZEN_PARAMS = {}
if MODE in ("BRAKES", "BRAKES_EXT"):
    # 7 starych z Fazy 5, tunujemy 4 brake-params
    default_frozen = "params/best/extended_best.json"
elif MODE == "VISION":
    # 7 starych + 4 brake-params z 6b-rev (11 total), tunujemy 5 vision-params
    default_frozen = "params/best/brakes_ext_best.json"
elif MODE == "JOINT":
    # Faza 6c: centrum search-space to wszystkie 16 params z vision_best.
    # FROZEN_PARAMS uzywamy tylko jako "centrum" (czytamy wartosci do wyliczenia bounds),
    # ale zaden param NIE jest tu zafrozowany - wszystkie sa tunowane jednoczesnie.
    default_frozen = "params/best/vision_best.json"
elif MODE == "JOINT64":
    # Faza 8: identyczna logika jak JOINT, ale przy 6 presses (~32x) zeby walidowac wyniki.
    default_frozen = "params/best/vision_best.json"
elif MODE == "ANTISLALOM":
    # Faza 7: 14 zafrozonych z vision_best (rollback po overfit JOINT 6c),
    # tunujemy APEX_SHIFT_GAIN + nowy APEX_SCALE (smooth tanh apex w my_racer.py).
    default_frozen = "params/best/vision_best.json"
elif MODE == "ABS":
    # Faza 9: Startujemy z vision_best (baseline) i tunujemy PID-y i trakcję
    default_frozen = "params/best/vision_best.json"
elif MODE == "JOINT_ABS":
    # Faza 10: Bierzemy komplet 21 najlepszych parametrów i szukamy wspólnych synergii
    default_frozen = "params/best/joint_abs.json"
else:
    default_frozen = None
if default_frozen is not None:
    frozen_path = os.environ.get("FROZEN_PARAMS_PATH", default_frozen)
    if not os.path.exists(frozen_path):
        raise FileNotFoundError(
            f"{MODE}=1 wymaga {frozen_path}. "
            "Albo ustaw FROZEN_PARAMS_PATH na inny plik."
        )
    with open(frozen_path, "r") as f:
        FROZEN_PARAMS = json.load(f)
    print(f"[Optuna] {MODE} mode: zafrozone {len(FROZEN_PARAMS)} params z {frozen_path}: {FROZEN_PARAMS}")
# =================================================

def run_torcs(params):
    global FIRST_RUN
    # Przekazanie genów (parametrów) do bota
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
    
    # Wydłużony czas na załadowanie gry do pamięci RAM przy pierwszym uruchomieniu
    if FIRST_RUN:
        time.sleep(8.0)
        FIRST_RUN = False
    else:
        time.sleep(5.0)
    
    # Szybka nawigacja do menu "Quick Race"
    for key in ['enter', 'enter', 'enter', 'enter']:
        pyautogui.press(key)
        time.sleep(0.2)
        
    time.sleep(1.0)
    os.chdir(cwd)
    
    # Symulowana klawiatura Numpad '+' (add) -> sim speedup. SPEEDUP_PRESSES kontroluje:
    # 8 presses = 128x (FULL/EXTENDED/.../JOINT/ANTISLALOM), 6 presses = ~32x (JOINT64, mniej overfit).
    for _ in range(SPEEDUP_PRESSES):
        pyautogui.press('add')
        time.sleep(0.1)
    
    print(f"Biegnie wyścig z Optuną! Oczekuję na wynik...")
    subprocess.run([sys.executable, "my_racer.py"])
    
    os.system('taskkill /f /im wtorcs.exe >nul 2>&1')
    time.sleep(0.5)
    
    # Odbiór wyniku od bota
    try:
        with open("last_lap.json", "r") as f:
            res = json.load(f)
            lap_time = res.get("lap_time", 9999.9)
            dist = res.get("dist_raced", 0)
    except Exception:
        lap_time = 9999.9
        dist = 0
        
    # jeśli bot się rozbił (DNF), dajemy mniejszą "karę" tym genom, które przejechały najwięcej metrów!
    if lap_time >= 9999.0:
        return 10000.0 - dist
        
    return lap_time

def objective(trial):
    if MODE == "SMOKE":
        # +/-20% wokol params_baseline.json (defaulty osiagaja 1:37.47 na Corkscrew)
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
        # Rozszerzone granice na nasycone parametry z Fazy 3:
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
        # Faza 6a: 7 starych params zafrozonych z params_extended_best.json,
        # tunujemy tylko 4 nowe params hamowania.
        params = dict(FROZEN_PARAMS)
        params["BRAKE_DISTANCE_LIN"]  = trial.suggest_float("BRAKE_DISTANCE_LIN",  0.20, 0.55)
        params["BRAKE_DISTANCE_QUAD"] = trial.suggest_float("BRAKE_DISTANCE_QUAD", 800.0, 2000.0)
        params["TRAIL_BRAKE_DIVISOR"] = trial.suggest_float("TRAIL_BRAKE_DIVISOR", 20.0, 80.0)
        params["BRAKE_PRESS_DIVISOR"] = trial.suggest_float("BRAKE_PRESS_DIVISOR", 25.0, 80.0)
    elif MODE == "BRAKES_EXT":
        # Faza 6b-rev: 7 starych zafrozone, brake-bounds rozszerzone w DOL bo 3/4 trafilo we floor w 6a.
        # TRAIL_BRAKE_DIVISOR zwezone (40 byl sweet spot, nie ma sensu szukac dalej od 80).
        params = dict(FROZEN_PARAMS)
        params["BRAKE_DISTANCE_LIN"]  = trial.suggest_float("BRAKE_DISTANCE_LIN",  0.10, 0.30)
        params["BRAKE_DISTANCE_QUAD"] = trial.suggest_float("BRAKE_DISTANCE_QUAD", 500.0, 1200.0)
        params["TRAIL_BRAKE_DIVISOR"] = trial.suggest_float("TRAIL_BRAKE_DIVISOR", 25.0, 60.0)
        params["BRAKE_PRESS_DIVISOR"] = trial.suggest_float("BRAKE_PRESS_DIVISOR", 15.0, 45.0)
    elif MODE == "VISION":
        # Faza 6b-vision: 11 zafrozone (7 stare + 4 brake-params z 6b-rev),
        # tunujemy 5 progow widzenia/predkosci. Constraint orderingu w if/elif:
        # VISION_MED < VISION_FAST < VISION_LONG (inaczej elifs sie zjadaja).
        # Suggest_float niezaleznie + invalid jak naruszone -> TPE sie nauczy.
        params = dict(FROZEN_PARAMS)
        v_long = trial.suggest_float("VISION_LONG_STRAIGHT", 100.0, 160.0)
        v_fast = trial.suggest_float("VISION_FAST_CORNER",   70.0, 110.0)
        v_med  = trial.suggest_float("VISION_MED_CORNER",    45.0,  80.0)
        if not (v_med < v_fast < v_long):
            # Niewazna kombinacja - zglos jako prune zeby TPE jej unikal
            raise optuna.TrialPruned()
        params["VISION_LONG_STRAIGHT"] = v_long
        params["VISION_FAST_CORNER"]   = v_fast
        params["VISION_MED_CORNER"]    = v_med
        params["SPEED_FAST_CORNER"]    = trial.suggest_float("SPEED_FAST_CORNER", 200.0, 270.0)
        params["SPEED_MED_CORNER"]     = trial.suggest_float("SPEED_MED_CORNER", 150.0, 230.0)
    elif MODE == "JOINT":
        # Faza 6c: joint refit, wszystkie 16 params w waskim ±10% wokol params_vision_best,
        # WYJATKI - 2 nasycenia z 6b-vision rozszerzone:
        #   SPEED_FAST_CORNER: 269.7 trafilo ceiling 270 -> rozszerzamy do 250-310
        #   VISION_MED_CORNER: 46.2 trafilo floor 45 -> rozszerzamy floor do 25
        # Centrum (FROZEN_PARAMS) odczytane z params_vision_best.json.
        # Constraint orderingu vision: VISION_MED < VISION_FAST < VISION_LONG (jak w VISION).
        c = FROZEN_PARAMS  # centrum, alias dla zwiezlosci
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
        # 2 nasycone -> rozszerzone bounds (a nie ±10%)
        params["SPEED_FAST_CORNER"]       = trial.suggest_float("SPEED_FAST_CORNER",       250.0, 310.0)
        params["VISION_MED_CORNER"]       = trial.suggest_float("VISION_MED_CORNER",        25.0,  60.0)
        # Constraint kolejnosci progow vision (jak w VISION mode)
        if not (params["VISION_MED_CORNER"] < params["VISION_FAST_CORNER"] < params["VISION_LONG_STRAIGHT"]):
            raise optuna.TrialPruned()
    elif MODE == "JOINT64":
        # Faza 8: identyczny search-space jak JOINT (±10% wokol vision_best, 2 nasycone rozszerzone),
        # ale wykonywany przy SPEEDUP_PRESSES=6 (~32x) zamiast 8 (~128x).
        # Cel: wyniki powinny byc walidowalne przy 1x (eliminacja overfit z JOINT 6c).
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
        # Faza 7: refactor calculate_steering -> smooth tanh apex (anti-slalom).
        # 14 params zafrozonych z params_vision_best.json (baseline 6b-vision, ~85.99-86.05s).
        # Tunujemy:
        #   APEX_SHIFT_GAIN: szeroki zakres bo smooth tanh ma inna czulosc niz bang-bang
        #   APEX_SCALE: nowy param, kontroluje jak szybko tanh saturuje (im mniejszy, tym ostrzej)
        params = dict(FROZEN_PARAMS)
        params["APEX_SHIFT_GAIN"] = trial.suggest_float("APEX_SHIFT_GAIN", 0.10, 0.80)
        # APEX_SCALE: szeroki zakres - male wartosci (~0.05) ~= bang-bang (vision_best baseline),
        # duze wartosci (>1.0) silnie tlumia oscylacje slalomu w mid-corner.
        # Sanity check przy 0.3 dal 3/5 DNF + 5s slowdown - wiec sweet spot albo 0.05 albo 1.0+.
        params["APEX_SCALE"]      = trial.suggest_float("APEX_SCALE",      0.05, 5.00)
    elif MODE == "ABS":
        # Optymalizacja dodanych kontrolerów PD/PID oraz TCS
        params = dict(FROZEN_PARAMS)
        params["ABS_SLIP_THRESHOLD"] = trial.suggest_float("ABS_SLIP_THRESHOLD", 1.0, 6.0)
        params["ABS_MODULATION"]     = trial.suggest_float("ABS_MODULATION", 0.1, 0.8)
        params["ABS_D_GAIN"]         = trial.suggest_float("ABS_D_GAIN", 0.0, 0.5)
        params["TCS_SLIP_THRESHOLD"] = trial.suggest_float("TCS_SLIP_THRESHOLD", 2.0, 10.0)
        params["STEER_D_GAIN"]       = trial.suggest_float("STEER_D_GAIN", 0.0, 5.0)
    elif MODE == "JOINT_ABS":
        # Faza 10: Wszystkie 21 parametrów jednocześnie wokół najlepszego przejazdu (abs_best.json)
        c = FROZEN_PARAMS
        params = {}
        # Wymuszamy wyższe granice dla prędkości maksymalnej, by Optuna znów szukała V-MAX
        params["TARGET_STRAIGHT_SPEED"]   = trial.suggest_float("TARGET_STRAIGHT_SPEED",   max(290.0, c["TARGET_STRAIGHT_SPEED"] * 0.95), 320.0)
        params["SAFE_SHARP_CORNER_SPEED"] = trial.suggest_float("SAFE_SHARP_CORNER_SPEED", 70.0, 85.0)
        params["MIN_NORMAL_CORNER_SPEED"] = trial.suggest_float("MIN_NORMAL_CORNER_SPEED", 80.0, 95.0)
        params["STEER_GAIN"]              = trial.suggest_float("STEER_GAIN",              c["STEER_GAIN"]              * 0.90, c["STEER_GAIN"]              * 1.10)
        params["CENTERING_GAIN"]          = trial.suggest_float("CENTERING_GAIN",          c["CENTERING_GAIN"]          * 0.80, c["CENTERING_GAIN"]          * 1.20)
        params["BRAKE_THRESHOLD"]         = trial.suggest_float("BRAKE_THRESHOLD",         c["BRAKE_THRESHOLD"]         * 0.90, c["BRAKE_THRESHOLD"]         * 1.10)
        params["APEX_SHIFT_GAIN"]         = trial.suggest_float("APEX_SHIFT_GAIN",         c["APEX_SHIFT_GAIN"]         * 0.90, c["APEX_SHIFT_GAIN"]         * 1.10)
        params["BRAKE_DISTANCE_LIN"]      = trial.suggest_float("BRAKE_DISTANCE_LIN",      c["BRAKE_DISTANCE_LIN"]      * 0.80, c["BRAKE_DISTANCE_LIN"]      * 1.30) # Zwiększono górny limit, by umożliwić dłuższe hamowanie
        params["BRAKE_DISTANCE_QUAD"]     = trial.suggest_float("BRAKE_DISTANCE_QUAD",     c["BRAKE_DISTANCE_QUAD"]     * 0.60, c["BRAKE_DISTANCE_QUAD"]     * 1.10) # ZMNIEJSZONY limit QUAD pozwala na znacząco WIEKSZY dystans hamowania (dzielenie)
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
        params["STEER_D_GAIN"]            = trial.suggest_float("STEER_D_GAIN",            0.0, 1.5) # Ograniczenie wysokich szarpnięć
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
    print(f"[Optuna] storage={STORAGE_URL} (Ctrl+C bezpieczne, ponowne uruchomienie wznowi badanie)")

    study = optuna.create_study(
        direction="minimize",
        storage=STORAGE_URL,
        study_name=STUDY_NAME,
        load_if_exists=True,
    )

    completed_before = len([t for t in study.trials if t.state.name == "COMPLETE"])
    print(f"[Optuna] juz ukonczonych prob w bazie: {completed_before}")

    try:
        study.optimize(objective, n_trials=N_TRIALS)
    except KeyboardInterrupt:
        print("\n[!] Przerwano optymalizacje przez uzytkownika (Ctrl+C).")

    print("\n================== ZAKONCZONO ==================")
    completed = [t for t in study.trials if t.state.name == "COMPLETE"]
    # DNF: obj zwraca 10000 - dist_raced (typowo 6000-9000); lap_time typowo 80-150 s
    dnf_count = sum(1 for t in completed if t.value is not None and t.value > 200.0)
    lap_count = len(completed) - dnf_count
    print(f"Prob zakonczonych: {len(completed)} / {len(study.trials)}, lap={lap_count}, DNF={dnf_count}")
    if lap_count > 0:
        lap_vals = sorted(t.value for t in completed if t.value is not None and t.value <= 200.0)
        print(f"Lap time stats: min={lap_vals[0]:.3f}, mean={sum(lap_vals)/len(lap_vals):.3f}, max={lap_vals[-1]:.3f}")

    try:
        print(f"Best params: {study.best_params}")
        print(f"Best lap_time: {study.best_value:.3f} s")
        # W trybie BRAKES (i przyszlych frozen-modach) study.best_params zawiera tylko
        # parametry zasugerowane przez trial.suggest_*. FROZEN_PARAMS musimy domergowac,
        # zeby my_racer.py mial KOMPLETNY 7+N zestaw (a nie defaulty zamiast 7 starych).
        full_params = {**FROZEN_PARAMS, **study.best_params}
        with open("params.json", "w") as f:
            json.dump(full_params, f, indent=4)
        if FROZEN_PARAMS:
            print(f"Zapisano params.json (merge: {len(FROZEN_PARAMS)} frozen + {len(study.best_params)} tuned).")
        else:
            print("Zapisano params.json.")
    except ValueError:
        print("Brak danych - zaden wyscig nie zostal w pelni ukonczony.")
