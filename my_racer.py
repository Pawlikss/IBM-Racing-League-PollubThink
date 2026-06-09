import snakeoil3_gym as snakeoil
import math
import json
import os
from logger import LogData, TelemetryLogger

STATE = {"prev_steer": 0.0, "prev_slip": 0.0}

# ================= CONFIGURATION PARAMETERS =================
PARAMS = {
    "TARGET_STRAIGHT_SPEED": 290.0,
    "SAFE_SHARP_CORNER_SPEED": 80.0,
    "MIN_NORMAL_CORNER_SPEED": 85.0,
    "STEER_GAIN": 30.0,
    "CENTERING_GAIN": 0.2,
    "BRAKE_THRESHOLD": 0.3,
    "APEX_SHIFT_GAIN": 0.46,
    "APEX_SCALE": 0.4,               # Increased for maximum smoothness (eliminates jitter!)
                                     # 0.05 ~= bang-bang for typical |bias|>0.15 (preserves vision_best baseline).
                                     # Optuna ANTISLALOM explores larger values for anti-slalom dampening.
    # Phase 6a - extracted from apply_brakes hardcoded values (for Optuna tuning)
    "BRAKE_DISTANCE_LIN": 0.35,      # linear multiplier of speedX for safe_distance
    "BRAKE_DISTANCE_QUAD": 1200.0,   # quadratic divisor of speedX^2 for safe_distance
    "TRAIL_BRAKE_DIVISOR": 40.0,     # exit_vision/X -> forgiveness during trail braking
    "BRAKE_PRESS_DIVISOR": 50.0,     # (safe-front)/(X*forgiveness) -> braking force
    # Phase 6b-vision - extracted from calculate_throttle hardcodes (for tuning)
    "VISION_LONG_STRAIGHT": 130.0,   # vision > X -> TARGET_STRAIGHT_SPEED
    "VISION_FAST_CORNER": 90.0,      # vision > X -> SPEED_FAST_CORNER
    "SPEED_FAST_CORNER": 240.0,      # km/h for wide curve
    "VISION_MED_CORNER": 60.0,       # vision > X -> SPEED_MED_CORNER
    "SPEED_MED_CORNER": 190.0,       # km/h for standard corner
    # ABS (Anti-lock Braking System)
    "ABS_SLIP_THRESHOLD": 3.0,       # Maximum speed difference (m/s) before ABS intervention
    "ABS_MODULATION": 0.4,           # How much to release the brake when wheels lock
    "ABS_D_GAIN": 0.1,               # D-Gain for ABS (modulation based on slip increase rate)
    "STEER_D_GAIN": 0.5,             # D-Gain for steering (Reduced from 2.0 to prevent jitter!)
    "TCS_SLIP_THRESHOLD": 5.0        # Wheel slip threshold for Traction Control System (TCS)
}

# Overwriting parameters by Optuna (if file exists)
if os.path.exists("params.json"):
    with open("params.json", "r") as f:
        try:
            loaded_params = json.load(f)
            PARAMS.update(loaded_params)
        except:
            pass

# ================= HELPER FUNCTIONS =================
def get_min_sensor_data(S):
    """Returns the minimum distance to the edge from left and right side"""
    left_sensors = S['track'][:9]
    right_sensors = S['track'][10:]

    min_left = min(left_sensors)
    min_right = min(right_sensors)
    return min(min_left, min_right)

def is_corner(S, min_reading):
    """Detects if the car is located in a corner"""
    # Wider viewing angle minimizes false corners on straights and hills
    # Removed bug (min_reading < 4.0) causing false corners near straight edges!
    open_path = max(S['track'][2:17])
    if open_path < 140.0:
        return True
    return False

# ================= CONTROL LOGIC =================
def calculate_steering(S, is_in_corner):
    dist = S.get('distFromStart', 0.0)
    # Blind drop zone in the chicane (Corkscrew). Optical radars see "sky" here.
    # Forcing maximum corner readiness BEFORE the drop starts, so the car doesn't jerk the steering wheel!
    is_chicane = 2370.0 < dist < 2500.0
    
    # Smoothly calculating how deep in the corner we are (0.0 = long straight, 1.0 = mid-corner)
    open_path = max(S['track'][2:17])
    exit_vision = max(S['track'][1:18])
    corner_intensity = max(0.0, min(1.0, (150.0 - open_path) / 50.0))
    if is_chicane:
        corner_intensity = 1.0 
    
    # True Out-In-Out: on corner exit, we allow drifting to the outside
    if exit_vision > 80.0 and corner_intensity > 0.0 and not is_chicane:
        current_centering = 0.02 # Minimal centering. Centrifugal force will push the car to the curb, but the bot won't hit the grass!
    else:
        current_centering = PARAMS["CENTERING_GAIN"] * (1.0 - 0.5 * corner_intensity)

    steer = (S['angle'] * PARAMS["STEER_GAIN"] / math.pi) - (S['trackPos'] * current_centering)

    # PD controller for steering. Heavily weakened on straights to prevent weaving!
    d_steer = steer - STATE["prev_steer"]
    STATE["prev_steer"] = steer
    
    current_d_gain = PARAMS.get("STEER_D_GAIN", 0.5) * (1.0 - 0.8 * corner_intensity)
    steer += d_steer * current_d_gain

    # Continuous speed dampener on the fastest straights
    if S['speedX'] > 90.0:
        speed_factor = S['speedX'] / 90.0
        if S['speedX'] > 150.0:
            speed_factor = (S['speedX'] / 90.0) ** 1.5
        steer = steer / speed_factor

    # Corner cutting activates ONLY when the car physically sees a corner (corner_intensity > 0.0).
    # On a straight, the multiplier is zero, which 100% eliminates any slip and left/right movement!
    if corner_intensity > 0.0:
        left_avg = sum(S['track'][:9]) / 9.0
        right_avg = sum(S['track'][10:]) / 9.0
        bias = right_avg - left_avg
        
        apex_gain = PARAMS.get("APEX_SHIFT_GAIN", 0.46) * corner_intensity
        if is_chicane:
            apex_gain *= 1.6 # Forcing a sharper turn in the chicane itself
            
        # Easing off "kiss the apex" on exit, which naturally throws the car to the outside!
        if exit_vision > 80.0 and not is_chicane:
            apex_gain *= 0.4 # Smoothed release, prevents sudden "letting go" of the steering wheel
            
        inside_dist = min(S['track'][:9]) if bias > 0 else min(S['track'][10:])
        # Slightly larger cushion (0.4m) so the inner wheel doesn't slip on the sand
        edge_factor = max(0.0, min(1.0, (inside_dist - 0.4) / 1.0))
        if is_chicane:
            edge_factor = 1.0 # In the Corkscrew, we ignore the cushion
            
        apex_scale = max(2.0, PARAMS.get("APEX_SCALE", 4.0))
        steer -= apex_gain * edge_factor * math.tanh(bias / apex_scale)
            
    return max(-1.0, min(1.0, steer))

def calculate_throttle(S, R):
    # Cut throttle if bot is still braking hard
    if R.get('brake', 0.0) > 0.1:
        return 0.0

    # 'corner_vision' looks ahead, and 'exit_vision' looks wide to the sides, searching for the curve exit.
    corner_vision = max(S['track'][4:15])
    exit_vision = max(S['track'][1:18])
    
    # Artificial vision "opening": if we see a straight to the side, we ignore the front wall!
    # Thanks to this, the bot will start accelerating (applying throttle immediately) already in mid-corner.
    vision = max(corner_vision, exit_vision * 0.95)
    
    # Fixing edge-case (hesitation on corner exit).
    if max(S['track'][8:11]) >= 150.0 or exit_vision > 75.0:
        vision = 200.0

    dist = S.get('distFromStart', 0.0)
    
    # Even later braking. We push full throttle up to 2180m!
    if 1950.0 < dist < 2280.0:
        vision = 200.0

    if vision > PARAMS["VISION_LONG_STRAIGHT"]:
        # Long straight, max speed (forcing a high limit ignoring any conservative Optuna values)
        target_speed = max(295.0, PARAMS.get("TARGET_STRAIGHT_SPEED", 290.0))
    elif vision > PARAMS["VISION_FAST_CORNER"]:
        # Wide, gentle corner that can be taken very fast
        target_speed = PARAMS["SPEED_FAST_CORNER"]
    elif vision > PARAMS["VISION_MED_CORNER"]:
        # Standard, fairly fast corner
        target_speed = PARAMS["SPEED_MED_CORNER"]
    elif vision > 35.0:
        # Speed limit for normal corners to prevent losing traction in 2nd gear
        target_speed = min(95.0, PARAMS.get("MIN_NORMAL_CORNER_SPEED", 90.0))
    else:
        # Speed limit for sharp corners
        target_speed = min(85.0, PARAMS.get("SAFE_SHARP_CORNER_SPEED", 80.0))

    # Tightened angle lock! When the car struggles in a corner, we reduce target speed more
    # to prevent understeer pushing it to the outside sand.
    if abs(S['angle']) > 0.5 and target_speed > PARAMS["MIN_NORMAL_CORNER_SPEED"]:
        target_speed = min(90.0, PARAMS.get("MIN_NORMAL_CORNER_SPEED", 90.0))

    is_chicane_area = 2400.0 < dist < 2500.0
    
    if is_chicane_area:
        target_speed = min(target_speed, 70.0) # Lower target so it doesn't hit 90 km/h before the drop

    speed_diff = target_speed - S['speedX']
    
    if speed_diff > 0:
        if speed_diff > 5:
            accel = 1.0
        else:
            accel = min(1.0, R.get('accel', 0.0) + 0.5)
    else:
        accel = max(0.0, R.get('accel', 0.0) - 0.2)

    slip = ((S['wheelSpinVel'][2] + S['wheelSpinVel'][3]) - (S['wheelSpinVel'][0] + S['wheelSpinVel'][1]))
    if slip > PARAMS.get("TCS_SLIP_THRESHOLD", 5.0) and S['speedX'] < 200.0:
        # If wheels lose traction, slowly subtracting -0.3 unloaded the rear causing sudden slip.
        # We cut throttle hard to a safe 10%, immediately stabilizing the car.
        accel = min(accel, 0.1)

    steer_mag = abs(R.get('steer', 0.0))
    # True, mathematical "Traction Circle".
    # Aggressive full throttle right at the corner apex (exit_vision > 55m)!
    # Exponent 3.5 = immediate 100% power upon steering return to center.
    exponent = 3.5 if exit_vision > 55.0 else 1.8
    max_allowed_accel = max(0.0, 1.0 - (steer_mag ** exponent))
    accel = min(accel, max_allowed_accel)

    if is_chicane_area:
        # CRITICAL: Absolute ban on throttle at the entry and blind drop!
        # Previously, after braking, the bot immediately accelerated in the air to 90 km/h, causing instant slip.
        if S['speedX'] > 70.0:
            accel = 0.0
        elif abs(S['angle']) > 0.1:
            accel = min(accel, 0.1)

    if S['speedX'] < 15:
        accel = 1.0

    return max(0.0, min(1.0, accel))

def apply_brakes(S, is_in_corner):
    brake = 0.0
    dist = S.get('distFromStart', 0.0)

    # Gentler braking due to angle error, applied only at high speeds.
    # Increased angle threshold prevents brake tapping during minor straight corrections (which killed V-MAX)!
    if abs(S['angle']) > PARAMS.get("BRAKE_THRESHOLD", 0.3) + 0.15 and S['speedX'] > 200:
        brake += 0.05

    # Front sensors assess distance to the wall ahead
    front_path = max(S['track'][7:12])
    # Wide sensors assess if there's an "escape" to the side (corner exit)
    exit_vision = max(S['track'][2:17])
    
    # Non-linear braking distance model. Saves the bot at highest speeds,
    # forcing much earlier braking using a quadratic formula:
    safe_distance = (S['speedX'] * PARAMS["BRAKE_DISTANCE_LIN"]) + (S['speedX'] ** 2) / PARAMS["BRAKE_DISTANCE_QUAD"]
    # Smooth extra distance multiplier for extreme speeds.
    # Earlier braking on straights! Increased coefficient to 0.25 (car won't overshoot).
    if S['speedX'] > 200.0:
        speed_factor = (S['speedX'] - 200.0) / 100.0 # from 0.0 at 200km/h to 1.0 at 300km/h
        safe_distance *= 1.0 + (0.25 * speed_factor)
    # Limit to 250m, provides an even larger margin for earlier braking at extreme V-MAX
    safe_distance = min(250.0, safe_distance)
    if front_path < safe_distance:
        # Trail Braking: If the side path is open (corner exit), drastically reduce braking force!
        forgiveness = max(1.0, exit_vision / PARAMS["TRAIL_BRAKE_DIVISOR"])
        # Fixed bug of duplicating multipliers (previously braking force dropped to ZERO!)
        if exit_vision > 80.0:
            forgiveness *= 2.0
        elif exit_vision > 50.0:
            forgiveness *= 1.4
        brake += min(1.0, (safe_distance - front_path) / (PARAMS["BRAKE_PRESS_DIVISOR"] * forgiveness))

    # Collision panic: restored 75 km/h threshold for hard braking
    if front_path < 25 and exit_vision < 45 and S['speedX'] > 75:
        brake += 0.8

    # Track-specific: Limit panic braking, but ONLY in the epicenter of the blind drop (2200-2350).
    # Earlier (2100-2200) bot MUST have 100% braking force to enter the corner slow enough!
    is_chicane_blind_drop = 2200.0 < dist < 2350.0
    if is_chicane_blind_drop:
        brake = min(brake, 0.4)

    # --- SYSTEM ABS (Anti-Lock Braking System) ---
    # Prevents front wheel lock-up, regaining steerability and reducing weaving.
    # Disable ABS in critical zone (wall < 30m) - better to lock wheels than fly off the track!
    if brake > 0.1 and S['speedX'] > 30.0 and front_path > 30.0:
        speed_ms = S['speedX'] / 3.6
        # F1 car wheel radius is roughly 0.33m. spinVel is in rad/s
        wheel_speed_ms = ((S['wheelSpinVel'][0] + S['wheelSpinVel'][1]) / 2.0) * 0.33 
        
        # ABS PID controller (using PD: slip threshold + slip rate)
        slip = speed_ms - wheel_speed_ms
        d_slip = slip - STATE.get("prev_slip", 0.0)
        STATE["prev_slip"] = slip

        if slip > PARAMS.get("ABS_SLIP_THRESHOLD", 3.0):
            # Limit D-term impact and guarantee brake never drops below 30% force!
            d_slip_clamped = max(-5.0, min(5.0, d_slip))
            modulation = PARAMS.get("ABS_MODULATION", 0.4) + (d_slip_clamped * PARAMS.get("ABS_D_GAIN", 0.1))
            brake = max(0.5, brake - modulation)
            
    # Protection against unnecessary micro-tapping of the brake
    if brake < 0.1:
        brake = 0.0

    return min(1.0, brake)

def shift_gears(S, R):
    current_gear = S.get('gear', 1)
    speed = S['speedX']
    
    if current_gear <= 0:
        return 1
        
    # Improved F1 gear ratios. Previously the car "bounced" off the rev limiter in 1st gear losing drive,
    # and shifted to 6th gear too early lacking power on straights!
    if current_gear == 1 and speed > 105: return 2
    if current_gear == 2 and speed > 145: return 3
    if current_gear == 3 and speed > 190: return 4
    if current_gear == 4 and speed > 230: return 5
    if current_gear == 5 and speed > 270: return 6
    
    # Aggressive engine braking (forced downshifts during heavy braking).
    if R.get('brake', 0.0) > 0.5:
        if current_gear == 6 and speed < 260: return 5
        if current_gear == 5 and speed < 215: return 4
        if current_gear == 4 and speed < 175: return 3
        if current_gear == 3 and speed < 130: return 2
        if current_gear == 2 and speed < 90:  return 1
    else:
        # SIGNIFICANTLY delayed downshifts (prevents "Gear Hunting" in fast corners!)
        if current_gear == 6 and speed < 250: return 5
        if current_gear == 5 and speed < 210: return 4
        if current_gear == 4 and speed < 165: return 3
        if current_gear == 3 and speed < 120: return 2
        if current_gear == 2 and speed < 80:  return 1
    
    return current_gear

# ================= MAIN DRIVER FUNCTION =================
def drive_modular(c):
    S, R = c.S.d, c.R.d
    
    min_sensor_data = get_min_sensor_data(S)
    in_corner = is_corner(S, min_sensor_data)
    
    R['steer'] = calculate_steering(S, in_corner)
    R['brake'] = apply_brakes(S, in_corner)
    R['accel'] = calculate_throttle(S, R)
    R['gear'] = shift_gears(S, R)

if __name__ == "__main__":
    C = snakeoil.Client(p=3001)
    logger = LogData()
    telemetry = TelemetryLogger()

    for step in range(C.maxSteps, 0, -1):
        C.get_servers_input()
        drive_modular(C)
        C.respond_to_server()

        S = C.S.d
        
        # Logging telemetry every 10 game engine steps
        if step % 10 == 0:
            in_corner = is_corner(S, get_min_sensor_data(S))
            telemetry.log_step([S.get('curLapTime', 0), S.get('distRaced', 0), S.get('speedX', 0), S.get('trackPos', 0), S.get('angle', 0), C.R.d['steer'], C.R.d['accel'], C.R.d['brake'], in_corner])

        if S.get('lastLapTime', 0) > 0:
            print(f"Finish line! Lap time: {S['lastLapTime']}")
            break
            
        if S.get('distRaced', 0) > 20 and S.get('speedX', 0) < 5 and step < C.maxSteps - 100:
            print("Car stuck! Aborting lap...")
            S['lastLapTime'] = 9999.9
            break
            
    final_lap_time = C.S.d.get('lastLapTime', 0)
    if final_lap_time == 0:
        final_lap_time = C.S.d.get('curLapTime', 9999.9)
        
    dist_raced = C.S.d.get('distRaced', 0)
    
    with open("last_lap.json", "w") as f:
        json.dump({"lap_time": final_lap_time, "dist_raced": dist_raced}, f)

    stats = [PARAMS["TARGET_STRAIGHT_SPEED"], PARAMS["SAFE_SHARP_CORNER_SPEED"], PARAMS["STEER_GAIN"], PARAMS["CENTERING_GAIN"], PARAMS["BRAKE_THRESHOLD"], final_lap_time, dist_raced]
    logger.log_data(stats)
    print(f"Log saved to CSV: Time {final_lap_time:.2f} (Distance: {dist_raced:.1f}m)")

    C.shutdown()