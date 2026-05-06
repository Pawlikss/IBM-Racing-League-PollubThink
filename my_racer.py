import snakeoil3_gym as snakeoil
import math
import json
import os
from logger import LogData, TelemetryLogger

STATE = {"prev_steer": 0.0, "prev_slip": 0.0}

# ================= PARAMETRY KONFIGURACYJNE =================
PARAMS = {
    "TARGET_STRAIGHT_SPEED": 290.0,
    "SAFE_SHARP_CORNER_SPEED": 80.0,
    "MIN_NORMAL_CORNER_SPEED": 85.0,
    "STEER_GAIN": 30.0,
    "CENTERING_GAIN": 0.2,
    "BRAKE_THRESHOLD": 0.3,
    "APEX_SHIFT_GAIN": 0.46,
    "APEX_SCALE": 0.4,               # Zwiekszono dla maksymalnej płynności (eliminuje szarpanie!)
                                     # 0.05 ~= bang-bang dla typowych |bias|>0.15 (preserves vision_best baseline).
                                     # Optuna ANTISLALOM eksploruje wieksze wartosci dla anti-slalom dampening.
    # Faza 6a - wyciagniete z hardkodow apply_brakes (do tunowania przez Optune)
    "BRAKE_DISTANCE_LIN": 0.35,      # mnoznik liniowy speedX dla safe_distance
    "BRAKE_DISTANCE_QUAD": 1200.0,   # dzielnik kwadratowy speedX^2 dla safe_distance
    "TRAIL_BRAKE_DIVISOR": 40.0,     # exit_vision/X -> forgiveness przy trail brakingu
    "BRAKE_PRESS_DIVISOR": 50.0,     # (safe-front)/(X*forgiveness) -> sila hamowania
    # Faza 6b-vision - wyciagniete z hardkodow calculate_throttle (do tunowania)
    "VISION_LONG_STRAIGHT": 130.0,   # vision > X -> TARGET_STRAIGHT_SPEED
    "VISION_FAST_CORNER": 90.0,      # vision > X -> SPEED_FAST_CORNER
    "SPEED_FAST_CORNER": 240.0,      # km/h dla szerokiego luku
    "VISION_MED_CORNER": 60.0,       # vision > X -> SPEED_MED_CORNER
    "SPEED_MED_CORNER": 190.0,       # km/h dla standardowego zakretu
    # ABS (System zapobiegający blokowaniu kół)
    "ABS_SLIP_THRESHOLD": 3.0,       # Maksymalna różnica prędkości (m/s) przed interwencją ABS
    "ABS_MODULATION": 0.4,           # O ile odpuścić hamulec gdy koła się zablokują
    "ABS_D_GAIN": 0.1,               # D-Gain dla ABS (modulacja w oparciu o szybkość narastania poślizgu)
    "STEER_D_GAIN": 0.5,             # D-Gain dla kierownicy (Zmniejszono z 2.0 by zapobiec szarpaniom!)
    "TCS_SLIP_THRESHOLD": 5.0        # Próg uślizgu kół dla Kontroli Trakcji (TCS)
}

# Nadpisywanie parametrów przez Optuna (jeśli plik istnieje)
if os.path.exists("params.json"):
    with open("params.json", "r") as f:
        try:
            loaded_params = json.load(f)
            PARAMS.update(loaded_params)
        except:
            pass

# ================= FUNKCJE POMOCNICZE =================
def get_min_sensor_data(S):
    """Zwraca najmniejszą odległość do krawędzi z lewej i prawej strony"""
    left_sensors = S['track'][:9]
    right_sensors = S['track'][10:]

    min_left = min(left_sensors)
    min_right = min(right_sensors)
    return min(min_left, min_right)

def is_corner(S, min_reading):
    """Wykrywa, czy samochód znajduje się w zakręcie"""
    # Szerszy kąt widzenia minimalizuje problem fałszywych zakrętów na prostych i pagórkach
    # Usunięto błąd (min_reading < 4.0), który wywoływał fałszywe zakręty przy krawędzi prostej!
    open_path = max(S['track'][2:17])
    if open_path < 140.0:
        return True
    return False

# ================= LOGIKA STEROWANIA =================
def calculate_steering(S, is_in_corner):
    dist = S.get('distFromStart', 0.0)
    # Strefa ślepego spadku w szykanie (Korkociąg). Optyczne radary widzą tutaj "niebo".
    # Wymuszamy maksymalną gotowość na zakręt ZANIM uskok się zacznie, żeby auto nie rzucało kierownicą!
    is_chicane = 2370.0 < dist < 2500.0
    
    # Płynnie wyliczamy, w jak głębokim zakręcie jesteśmy (0.0 = długa prosta, 1.0 = środek zakrętu)
    open_path = max(S['track'][2:17])
    corner_intensity = max(0.0, min(1.0, (150.0 - open_path) / 50.0))
    if is_chicane:
        corner_intensity = 1.0 
    
    current_centering = PARAMS["CENTERING_GAIN"] * (1.0 - 0.5 * corner_intensity)

    steer = (S['angle'] * PARAMS["STEER_GAIN"] / math.pi) - (S['trackPos'] * current_centering)

    # Kontroler PD dla kierownicy. Mocno osłabiamy na prostych, by zapobiec wężykowaniu!
    d_steer = steer - STATE["prev_steer"]
    STATE["prev_steer"] = steer
    
    current_d_gain = PARAMS.get("STEER_D_GAIN", 0.5) * (1.0 - 0.8 * corner_intensity)
    steer += d_steer * current_d_gain

    # Ciągły tłumik prędkościowy na najszybszych prostych
    if S['speedX'] > 90.0:
        speed_factor = S['speedX'] / 90.0
        if S['speedX'] > 150.0:
            speed_factor = (S['speedX'] / 90.0) ** 1.5
        steer = steer / speed_factor

    # Cięcie zakrętu uaktywnia się TYLKO gdy auto fizycznie widzi zakręt (corner_intensity > 0.0). 
    # Na prostej mnożnik z automatu wynosi zero, co w 100% zlikwiduje jakikolwiek uślizg i lewo/prawo!
    if corner_intensity > 0.0:
        left_avg = sum(S['track'][:9]) / 9.0
        right_avg = sum(S['track'][10:]) / 9.0
        bias = right_avg - left_avg
        
        apex_gain = PARAMS.get("APEX_SHIFT_GAIN", 0.46) * corner_intensity
        if is_chicane:
            apex_gain *= 1.6 # Wymuszamy mocniejsze łamanie auta na samej szykanie
            
        inside_dist = min(S['track'][:9]) if bias > 0 else min(S['track'][10:])
        # Poduszka, żeby nie wjeżdżał w żwir, ale bardzo ciasno dokręcał do trawy (od 2.0m do 0.8m)
        edge_factor = max(0.0, min(1.0, (inside_dist - 0.8) / 1.2))
        if is_chicane:
            edge_factor = 1.0 # W Korkociągu ignorujemy poduszkę
            
        apex_scale = max(2.0, PARAMS.get("APEX_SCALE", 4.0))
        steer -= apex_gain * edge_factor * math.tanh(bias / apex_scale)
            
    return max(-1.0, min(1.0, steer))

def calculate_throttle(S, R):
    # Odcięcie gazu jeśli bot wciąż ostro hamuje
    if R.get('brake', 0.0) > 0.1:
        return 0.0

    # 'corner_vision' patrzy przed siebie, a 'exit_vision' szeroko na boki, szukając wyjścia z łuku.
    corner_vision = max(S['track'][4:15])
    exit_vision = max(S['track'][1:18])
    
    # Sztuczne "otwarcie" wizji: jeśli bokiem widzimy prostą, ignorujemy ścianę z przodu!
    # Dzięki temu bot zacznie przyspieszać (od razu doda gazu) już w środku zakrętu.
    vision = max(corner_vision, exit_vision * 0.95)
    
    # Łatanie edge-case'a z bloga (hesitation na wyjściu z zakrętu).
    if max(S['track'][8:11]) >= 150.0 or exit_vision > 75.0:
        vision = 200.0

    dist = S.get('distFromStart', 0.0)
    
    # Jeszcze późniejsze dohamowanie. Tniemy do 2180m na pełnym gazie!
    if 1950.0 < dist < 2280.0:
        vision = 200.0

    if vision > PARAMS["VISION_LONG_STRAIGHT"]:
        # Długa prosta, jedziemy na maksa (wymuszamy wysoki limit ignorując ewentualne zachowawcze wartości Optuny)
        target_speed = max(295.0, PARAMS.get("TARGET_STRAIGHT_SPEED", 290.0))
    elif vision > PARAMS["VISION_FAST_CORNER"]:
        # Szeroki, łagodny zakręt, który można pokonać bardzo szybko
        target_speed = PARAMS["SPEED_FAST_CORNER"]
    elif vision > PARAMS["VISION_MED_CORNER"]:
        # Standardowy, dość szybki zakręt
        target_speed = PARAMS["SPEED_MED_CORNER"]
    elif vision > 35.0:
        # Ograniczenie prędkości dla normalnych zakrętów, żeby nie zrywać przyczepności na 2. biegu
        target_speed = min(95.0, PARAMS.get("MIN_NORMAL_CORNER_SPEED", 90.0))
    else:
        # Ograniczenie prędkości dla ostrych zakrętów
        target_speed = min(85.0, PARAMS.get("SAFE_SHARP_CORNER_SPEED", 80.0))

    # Zacieśniona blokada kąta! Kiedy auto walczy w zakręcie, mocniej zdejmujemy target speed
    # by zapobiec ucieczce zjawiskiem podsterowności na zewnętrzny piasek.
    if abs(S['angle']) > 0.5 and target_speed > PARAMS["MIN_NORMAL_CORNER_SPEED"]:
        target_speed = min(90.0, PARAMS.get("MIN_NORMAL_CORNER_SPEED", 90.0))

    is_chicane_area = 2400.0 < dist < 2500.0
    
    if is_chicane_area:
        target_speed = min(target_speed, 70.0) # Niższy cel, żeby nie dobijał do 90 km/h przed zjazdem

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
        # Jeśli koła zerwą trakcję, powolne odejmowanie -0.3 odciążało tył wywołując nagły uślizg.
        # Ucinamy gaz twardo do bezpiecznych 10%, natychmiastowo stabilizując bolid.
        accel = min(accel, 0.1)

    steer_mag = abs(R.get('steer', 0.0))
    # Prawdziwe, matematyczne "Traction Circle" (Koło Przyczepności).
    # Zamiast sztywnego progu skokowego, ucinamy gaz całkowicie PŁYNNIE na całej szerokości zakrętu.
    # Eliminuje to gwałtowne zrzuty mocy, zapobiegając niebezpiecznym transferom masy i bączkom!
    max_allowed_accel = max(0.0, 1.0 - (steer_mag ** 1.2))
    accel = min(accel, max_allowed_accel)

    if is_chicane_area:
        # KLUCZOWE: Całkowity zakaz dodawania gazu na wejściu i ślepym zjeździe! 
        # Wcześniej po dohamowaniu bot od razu przyspieszał w locie do 90 km/h, co wywoływało natychmiastowy poślizg.
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

    # Łagodniejsze hamowanie z powodu błędu kąta, aplikowane tylko na dużej prędkości.
    # Zwiększony próg kąta zapobiega muskaniu hamulca przy drobnych korektach na prostych (co zabijało V-MAX)!
    if abs(S['angle']) > PARAMS.get("BRAKE_THRESHOLD", 0.3) + 0.15 and S['speedX'] > 200:
        brake += 0.05

    # Czujniki z przodu oceniają dystans do bandy na wprost
    front_path = max(S['track'][7:12])
    # Szerokie czujniki oceniają, czy jest "ucieczka" z boku (wyjście z zakrętu)
    exit_vision = max(S['track'][2:17])
    
    # Nieliniowy model dystansu hamowania. Ratuje bota przy najwyższych prędkościach,
    # wymuszając hamowanie z dużo większego wyprzedzenia ze wzoru kwadratowego:
    safe_distance = (S['speedX'] * PARAMS["BRAKE_DISTANCE_LIN"]) + (S['speedX'] ** 2) / PARAMS["BRAKE_DISTANCE_QUAD"]
    # Płynny ekstra mnożnik dystansu dla ekstremalnych prędkości.
    # Zredukowany z 0.4 do 0.2, żeby bot nie zwalniał za wcześnie po osiągnięciu upragnionych 260-270 km/h!
    if S['speedX'] > 200.0:
        speed_factor = (S['speedX'] - 200.0) / 100.0 # od 0.0 przy 200km/h do 1.0 przy 300km/h
        safe_distance *= 1.0 + (0.2 * speed_factor)
    # Ograniczenie do 250m, daje jeszcze większy margines na wcześniejsze hamowanie przy ekstremalnych V-MAX
    safe_distance = min(250.0, safe_distance)
    if front_path < safe_distance:
        # Trail Braking: Jeśli z boku jest otwarta droga (exit z łuku), drastycznie redukujemy siłę hamowania!
        forgiveness = max(1.0, exit_vision / PARAMS["TRAIL_BRAKE_DIVISOR"])
        # Jeszcze silniejsza redukcja hamowania na wyjściach, gdzie mamy wolną przestrzeń
        if exit_vision > 80.0:
            forgiveness *= 2.5
        elif exit_vision > 50.0:
            forgiveness *= 1.5
        brake += min(1.0, (safe_distance - front_path) / (PARAMS["BRAKE_PRESS_DIVISOR"] * forgiveness))

    # Panika przed zderzeniem: przywrócono próg 75 km/h dla mocnego hamowania
    if front_path < 25 and exit_vision < 45 and S['speedX'] > 75:
        brake += 0.8

    # Track-specific: Ograniczamy paniczne hamowanie, ale TYLKO w epicentrum ślepego uskoku (2200-2350).
    # Wcześniej (2100-2200) bot MUSI mieć 100% siły hamulców, żeby wejść w zakręt odpowiednio wolno!
    is_chicane_blind_drop = 2200.0 < dist < 2350.0
    if is_chicane_blind_drop:
        brake = min(brake, 0.4)

    # --- SYSTEM ABS (Anti-Lock Braking System) ---
    # Zapobiega blokowaniu przednich kół (lock-up), co odzyskuje sterowność i redukuje wężykowanie.
    # Wyłączamy ABS w strefie krytycznej (ściana < 30m) - lepiej zablokować koła niż wylecieć poza tor!
    if brake > 0.1 and S['speedX'] > 30.0 and front_path > 30.0:
        speed_ms = S['speedX'] / 3.6
        # Promień koła w F1 car to około 0.33m. spinVel jest w rad/s
        wheel_speed_ms = ((S['wheelSpinVel'][0] + S['wheelSpinVel'][1]) / 2.0) * 0.33 
        
        # ABS PID controller (wykorzystujemy PD: próg poślizgu + tempo jego narastania z bloga)
        slip = speed_ms - wheel_speed_ms
        d_slip = slip - STATE.get("prev_slip", 0.0)
        STATE["prev_slip"] = slip

        if slip > PARAMS.get("ABS_SLIP_THRESHOLD", 3.0):
            # Limitujemy wpływ członu D i gwarantujemy, że hamulec nigdy nie spadnie poniżej 30% siły!
            d_slip_clamped = max(-5.0, min(5.0, d_slip))
            modulation = PARAMS.get("ABS_MODULATION", 0.4) + (d_slip_clamped * PARAMS.get("ABS_D_GAIN", 0.1))
            brake = max(0.5, brake - modulation)
            
    # Zabezpieczenie przed niepotrzebnym mikromuskaniem hamulca
    if brake < 0.1:
        brake = 0.0

    return min(1.0, brake)

def shift_gears(S, R):
    current_gear = S.get('gear', 1)
    speed = S['speedX']
    
    if current_gear <= 0:
        return 1
        
    # Histereza - Opóźnione zmiany na wyższy bieg (wyższy moment obrotowy i lepsze przyspieszenie)
    if current_gear == 1 and speed > 114: return 2
    if current_gear == 2 and speed > 153: return 3
    if current_gear == 3 and speed > 193: return 4
    if current_gear == 4 and speed > 237: return 5
    if current_gear == 5 and speed > 248: return 6
    
    # Agresywne hamowanie silnikiem (wymuszone zrzutki przy ostrym hamowaniu) zgodnie z blogiem
    if R.get('brake', 0.0) > 0.5:
        if current_gear == 6 and speed < 249: return 5
        if current_gear == 5 and speed < 222: return 4
        if current_gear == 4 and speed < 178: return 3
        if current_gear == 3 and speed < 138: return 2
        if current_gear == 2 and speed < 97:  return 1
    else:
        # ZNACZNIE opóźnione redukcje (zapobiega to zjawisku "Gear Hunting" na szybkich łukach!)
        if current_gear == 6 and speed < 235: return 5
        if current_gear == 5 and speed < 205: return 4
        if current_gear == 4 and speed < 160: return 3
        if current_gear == 3 and speed < 115: return 2
        if current_gear == 2 and speed < 75:  return 1
    
    return current_gear

# ================= GŁÓWNA FUNKCJA KIEROWCY =================
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
        
        # Rejestrowanie telemetrii co 10 kroków silnika gry
        if step % 10 == 0:
            in_corner = is_corner(S, get_min_sensor_data(S))
            telemetry.log_step([S.get('curLapTime', 0), S.get('distRaced', 0), S.get('speedX', 0), S.get('trackPos', 0), S.get('angle', 0), C.R.d['steer'], C.R.d['accel'], C.R.d['brake'], in_corner])

        if S.get('lastLapTime', 0) > 0:
            print(f"Meta! Czas okrążenia: {S['lastLapTime']}")
            break
            
        if S.get('distRaced', 0) > 20 and S.get('speedX', 0) < 5 and step < C.maxSteps - 100:
            print("Samochód utknął! Przerywam okrążenie...")
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
    print(f"Zapisano log do CSV: Czas {final_lap_time:.2f} (Dystans: {dist_raced:.1f}m)")

    C.shutdown()