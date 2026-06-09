# Parameters Dictionary for `my_racer.py`

All configurable parameters of the controller. Defined in the `PARAMS` dict within
../my_racer.py, and overwritten by `params.json` (root) if it exists.

Optuna in ../optimize.py tunes a subset of these parameters depending
on the MODE (env var) — see comments in optimize.py above the MODE section.

---

## Directory Structure `params/`

```
params/
├── PARAMS.md           ← TEN PLIK (dictionary)
├── baseline.json       ← oryginalne defaulty (1:37.47 na Corkscrew)
├── best/               ← najlepsze wyniki z każdej fazy Optuny
│   ├── smoke_best.json       (Faza 2, ~1:35)
│   ├── full_best.json        (Faza 3, ~1:30.86)
│   ├── extended_best.json    (Faza 5, ~1:29.24)
│   ├── brakes_best.json      (Faza 6a, ~1:27.34)
│   ├── brakes_ext_best.json  (Faza 6b-rev, ~1:26.69)
│   ├── vision_best.json      (Faza 6b-vision, 1:26.05) ← AKTYWNY BASELINE
│   ├── joint_best.json       (Faza 6c, 1:25.16 @ 128x ale 5/5 DNF @ 1x — overfit artefakt)
│   └── antislalom_best.json  (Faza 7, 1:29.57 — failure artefakt)
└── snapshots/          ← kopie params.json sprzed kolejnych faz (rollback tickets)
    ├── pre_faza6a.json
    ├── pre_faza6b.json
    ├── pre_faza6c.json
    ├── pre_faza6vision.json
    └── pre_antislalom_run.json
```

`params.json` w root to **runtime config** (czytany przez `my_racer.py`). Optuna
nadpisuje go po każdym best trial. Aby przywrócić baseline:

```powershell
copy params\best\vision_best.json params.json
```

---

## Parametry sterowania (steering)

### `STEER_GAIN` — czułość lookahead steering

- **Typ:** float, **Default:** 30.0, **Sweet spot:** ~5.10 (vision_best)
- **Opis:** Mnożnik dla sygnału lookahead steeringu. Im większy, tym mocniej bot
  skręca w odpowiedzi na zakrzywienie toru widziane przez vision sensors.
- **Optuna ranges:** SMOKE [24, 36], FULL/EXTENDED [5, 45]
- **Insight:** W Fazie 3 trafił floor 15 → rozszerzenie do 5 dało Fazę 5 (1:29.24).
  Optymalna wartość dużo niższa niż intuicyjna 30.

### `CENTERING_GAIN` — siła powrotu na środek toru

- **Typ:** float, **Default:** 0.2, **Sweet spot:** ~0.048 (vision_best)
- **Opis:** Dodatek do `steer` proporcjonalny do `trackPos` (pozycja na torze).
  0.0 = brak centrowania, 0.4 = silne ściąganie do osi.
- **Optuna ranges:** EXTENDED/FULL [0.0, 0.4]
- **Insight:** Też trafił floor (0.056) w Fazie 3. Bot z minimal centerwoględem
  jeździ szybciej bo nie walczy z own apex shift.

### `APEX_SHIFT_GAIN` — agresywność cięcia apex

- **Typ:** float, **Default:** 0.46, **Sweet spot:** ~0.454 (vision_best)
- **Opis:** Maksymalne przesunięcie targetu w stronę apex w `calculate_steering`.
  Wyższe = ostrzejsze cięcie do wewnętrznej krawędzi w zakrętach.
- **Optuna ranges:** [0.1, 0.8]

### `APEX_SCALE` — tłumik smooth-tanh apex (Faza 7)

- **Typ:** float, **Default:** 0.05, **Sweet spot:** nieznany (Faza 7 fail)
- **Opis:** Skala dla `tanh(bias / APEX_SCALE)` w smooth apex shift. Małe wartości
  (~0.05) → ~bang-bang (jak vision_best). Duże (>1.0) → silne tłumienie oscylacji
  w mid-corner.
- **Faza 7 wynik:** APEX_SCALE=2.106 wygrał, ale +3.5s/lap kosztu i 3% pass rate.
  Smooth tanh jako anti-slalom fix nie działa.

---

## Parametry prędkości (speed targets)

### `TARGET_STRAIGHT_SPEED` — prędkość docelowa na prostej

- **Typ:** float (km/h), **Default:** 290.0, **Sweet spot:** ~279.7 (vision_best)
- **Opis:** Top speed gdy `vision > VISION_LONG_STRAIGHT`. Bot trzyma pełen gaz aż
  do tej prędkości.
- **Optuna ranges:** EXTENDED/FULL [240, 310]

### `SPEED_FAST_CORNER` — prędkość w szybkich łukach

- **Typ:** float (km/h), **Default:** 240.0, **Sweet spot:** ~269.7 (trafił ceiling)
- **Opis:** Target speed gdy `vision > VISION_FAST_CORNER` ale `< VISION_LONG_STRAIGHT`.
- **Optuna ranges:** VISION [200, 270], JOINT [250, 310] (rozszerzony po nasyceniu)

### `SPEED_MED_CORNER` — prędkość w średnich zakrętach

- **Typ:** float (km/h), **Default:** 190.0, **Sweet spot:** ~213.7 (vision_best)
- **Opis:** Target speed gdy `vision > VISION_MED_CORNER` ale `< VISION_FAST_CORNER`.
- **Optuna ranges:** VISION [150, 230]

### `MIN_NORMAL_CORNER_SPEED` — dolny próg prędkości w zakręcie normalnym

- **Typ:** float (km/h), **Default:** 110.0, **Sweet spot:** ~117.5 (vision_best)
- **Opis:** Minimalna prędkość w "normal corner" (vision pomiędzy MED a FAST progami).
  W Fazie 3 trafił ceiling 150 → rozszerzenie do 180.
- **Optuna ranges:** EXTENDED [90, 180]

### `SAFE_SHARP_CORNER_SPEED` — prędkość w ostrym zakręcie

- **Typ:** float (km/h), **Default:** 60.0, **Sweet spot:** ~83.7 (vision_best)
- **Opis:** Target speed gdy `vision <= VISION_MED_CORNER` (bot widzi ostry zakręt
  blisko). Lower = bezpieczniej, ale tracimy czas.
- **Optuna ranges:** EXTENDED [40, 95]

---

## Parametry vision (progi widzenia)

> **Constraint orderingu:** `VISION_MED < VISION_FAST < VISION_LONG`. Optuna używa
> `optuna.TrialPruned()` żeby wyrzucać niepoprawne kombinacje.

### `VISION_LONG_STRAIGHT` — próg "to jest prosta"

- **Typ:** float (m), **Default:** 130.0, **Sweet spot:** ~127.5 (vision_best)
- **Opis:** Jeśli `vision > X`, traktujemy odcinek jako prostą i celujemy
  TARGET_STRAIGHT_SPEED.
- **Optuna ranges:** [100, 160]

### `VISION_FAST_CORNER` — próg "to jest szybki łuk"

- **Typ:** float (m), **Default:** 90.0, **Sweet spot:** ~103.0 (vision_best)
- **Opis:** Pomiędzy tym a LONG_STRAIGHT → SPEED_FAST_CORNER.
- **Optuna ranges:** [70, 110]

### `VISION_MED_CORNER` — próg "to jest średni zakręt"

- **Typ:** float (m), **Default:** 60.0, **Sweet spot:** ~46.2 (trafił floor 45)
- **Opis:** Pomiędzy tym a FAST_CORNER → SPEED_MED_CORNER. Poniżej tego → ostry
  zakręt, redukcja do SAFE_SHARP_CORNER_SPEED.
- **Optuna ranges:** VISION [45, 80], JOINT [25, 60] (rozszerzony floor po nasyceniu)

---

## Parametry hamowania (Faza 6a)

### `BRAKE_THRESHOLD` — próg "trzeba hamować"

- **Typ:** float, **Default:** 0.3, **Sweet spot:** ~0.273 (vision_best)
- **Opis:** Jeśli `current_speed > target_speed * (1 + BRAKE_THRESHOLD)`, włącza
  hamowanie. Niższe = wcześniejsze hamowanie, wyższe = trail-braking pod sam apex.
- **Optuna ranges:** EXTENDED [0.1, 0.5]

### `BRAKE_DISTANCE_LIN` — liniowy mnożnik dystansu hamowania

- **Typ:** float, **Default:** 0.35, **Sweet spot:** ~0.224 (vision_best)
- **Opis:** Część `safe_distance = LIN * speedX + speedX² / QUAD`. Większy LIN =
  bardziej liniowo skalowane hamowanie z prędkością.
- **Optuna ranges:** BRAKES_EXT [0.10, 0.30]

### `BRAKE_DISTANCE_QUAD` — kwadratowy dzielnik dystansu hamowania

- **Typ:** float, **Default:** 1200.0, **Sweet spot:** ~1025 (vision_best)
- **Opis:** Część `safe_distance = LIN * speedX + speedX² / QUAD`. Mniejszy QUAD =
  drastyczniejsze skalowanie z prędkością².
- **Optuna ranges:** BRAKES_EXT [500, 1200]

### `TRAIL_BRAKE_DIVISOR` — forgiveness w trail brakingu

- **Typ:** float, **Default:** 40.0, **Sweet spot:** ~49.5 (vision_best)
- **Opis:** Część `forgiveness = exit_vision / DIV`. Większy DIV = mniej forgiveness,
  bot puszcza hamulec później (agresywniej trail-braking pod apex).
- **Optuna ranges:** BRAKES_EXT [25, 60]

### `BRAKE_PRESS_DIVISOR` — siła wciskania hamulca

- **Typ:** float, **Default:** 45.0, **Sweet spot:** ~17.5 (vision_best, trafił floor)
- **Opis:** Część `brake = (safe-front) / (DIV * forgiveness)`. Mniejszy DIV =
  silniejsze hamowanie. Trafił dolne granice w Fazach 6a/6b → rozszerzony floor 15.
- **Optuna ranges:** BRAKES_EXT [15, 45]
- **Insight:** 3 z 4 brake-params trafiły floor → bot chce hamować mocniej i
  agresywniej niż defaulty zakładały.

---

## Tabela: gdzie zostaje co

| Parameter               | Gdzie używane w `my_racer.py`        | Faza tuningu  |
| ----------------------- | ------------------------------------ | ------------- |
| TARGET_STRAIGHT_SPEED   | `calculate_throttle` (top speed)     | 3, 5, 6c      |
| SAFE_SHARP_CORNER_SPEED | `calculate_throttle` (sharp corner)  | 3, 5, 6c      |
| MIN_NORMAL_CORNER_SPEED | `calculate_throttle` (normal corner) | 3, 5, 6c      |
| STEER_GAIN              | `calculate_steering` (lookahead)     | 3, 5, 6c      |
| CENTERING_GAIN          | `calculate_steering` (trackPos)      | 3, 5, 6c      |
| BRAKE_THRESHOLD         | `apply_brakes` (kiedy hamować)       | 3, 5, 6c      |
| APEX_SHIFT_GAIN         | `calculate_steering` (apex bias)     | 3, 5, 6c, 7   |
| APEX_SCALE              | `calculate_steering` (smooth tanh)   | 7 (failed)    |
| BRAKE_DISTANCE_LIN      | `apply_brakes` (safe_distance)       | 6a, 6b, 6c    |
| BRAKE_DISTANCE_QUAD     | `apply_brakes` (safe_distance)       | 6a, 6b, 6c    |
| TRAIL_BRAKE_DIVISOR     | `apply_brakes` (forgiveness)         | 6a, 6b, 6c    |
| BRAKE_PRESS_DIVISOR     | `apply_brakes` (brake force)         | 6a, 6b, 6c    |
| VISION_LONG_STRAIGHT    | `calculate_throttle` (próg prosta)   | 6b-vision, 6c |
| VISION_FAST_CORNER      | `calculate_throttle` (próg fast)     | 6b-vision, 6c |
| VISION_MED_CORNER       | `calculate_throttle` (próg med)      | 6b-vision, 6c |
| SPEED_FAST_CORNER       | `calculate_throttle` (cel fast)      | 6b-vision, 6c |
| SPEED_MED_CORNER        | `calculate_throttle` (cel med)       | 6b-vision, 6c |

---

## Konwencje pracy

1. **NIE NADPISYWAĆ** `params/best/vision_best.json` — to nasz złoty 1:26 baseline.
2. **Snapshot przed każdą nową fazą Optuny:** `copy params.json params\snapshots\pre_fazaXX.json`.
3. **Po Optunie:** najlepszy wynik kopiuj do `params/best/<faza>_best.json`, runtime
   `params.json` zostaje aktywny.
4. **Walidacja po każdej fazie:** `python startup.py` (5x1x). Tylko walidowane
   wyniki uznajemy za "działa".
5. **Failed experiments (overfit/regresja):** zachowujemy w `params/best/` z
   adnotacją w PLAN.md, że to artefakt — nie usuwamy, są wartościowe jako
   kontrprzykłady.
