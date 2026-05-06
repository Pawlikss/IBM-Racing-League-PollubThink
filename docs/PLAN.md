# Plan działania – IBM-TORCS-Think2 → 1:30 na Corkscrew z car1-ow1

> **Status:** zatwierdzony 2026-04-25.
> **Cel nadrzędny:** przejazd Corkscrew w czasie ≤ 1:30 z autem **car1-ow1** (F1-style),
> na bazie ręcznie napisanego kontrolera reaktywnego (`my_racer.py`)
> tunowanego przez **Optunę** (TPE Bayesian).

## Dlaczego ten plan zamiast SAC/IL z poprzedniego repo (`IBM-TORCS-Think`)

- SAC + warmstart z gap-steering eksperta po 230k krokach dopiero zaczął wychodzić z lokalnego
  minimum (ep_rew_mean ~3 → 88 w ostatnich 15k krokach), realny ETA do 1:30 to kolejne 1.5–3 M kroków
  + reward shaping.
- Tutaj kontroler już *jeździ* (heurystyki: lookahead steering, apex shifting, multi-tier target speed,
  trail braking, TCS, pełna skrzynia). Optuna stroi tylko 8 floatów w 128× sim speed.
- Asymetria nakładu: dni vs. godziny CPU.
- RL nie jest porzucone – zostaje jako Faza 7 (`my_racer-as-expert` zamiast słabszego gap-steering).

## Założenia (z Q&A 2026-04-25)

- Tor: tylko Corkscrew (road).
- Auto: tylko car1-ow1 (już ustawione w `torcs/drivers/scr_server/scr_server.xml` slot 0).
- Target: lap_time ≤ 1:30 (acceptable: ≤ 1:35 z Fazą 5).
- TORCS install (`./torcs/`) skopiowany ręcznie i ma trafić do gita (519 MB, 2530 plików).
- PyAutoGUI launch (startup.py / optimize.py wciska klawisze w okno gry) zostaje – wracamy do tego później jeśli zawodzi.
- Reward func Optuny (`if DNF: return 10000 - dist`) zostaje – ewentualnie zaostrzymy w Fazie 6.

---

## Faza 0 — Setup & sanity *(M, 1-2h)*

**Cel:** repo komituje się, baseline z defaultami startuje i jedzie.

1. **Git: tracking `torcs/`**
   - `.gitignore`: usunąć `torcs/`, dodać wyjątki na runtime artefakty (`torcs/results/`, `torcs/config/screen.xml`, `*.log`).
   - Sprawdzić rozmiary: 519 MB total, brak plików >50 MB → plain git OK, LFS niepotrzebne.
   - `git add torcs/ .gitignore practice.xml && git commit`.
2. **Tor: Corkscrew w `practice.xml`**
   - `torcs/config/raceman/practice.xml` już ustawiony (skopiowane z Think).
   - Root `practice.xml` zaktualizować dla spójności (michigan→corkscrew, inferno→scr_server).
3. **Auto: car1-ow1**
   - `torcs/drivers/scr_server/scr_server.xml` slot 0 ma `car name="car1-ow1"` ✓.
4. **Smoke run:** `python startup.py` (jeden wyścig).
   - Obserwować: menu, połączenie SCR na 3001, ruch auta, dojazd.
   - Efekt: `recordings.csv` ma wiersz, `last_lap.json` istnieje.
   - **Gate:** jak nie działa → Faza 0.5.

**Deliverable:** baseline lap_time z PARAMS=defaults. Oczekiwane 1:50–2:30 lub DNF (defaulty pewnie były pod inne auto/tor).

## Faza 0.5 — Debug baseline *(opcjonalna, 0-3h)*

Najczęstsze problemy:
- **PyAutoGUI nie trafia w menu** → ręcznie raz dojść do "Race", dalsze runy startup.py odpalają tylko grę.
- **Auto rzuca salto** (car1-ow1 = F1, niskie aero) → safe baseline:
  `APEX_SHIFT_GAIN=0.2`, `CENTERING_GAIN=0.3`, `STEER_GAIN=22`.
- **Server SCR słucha na innym slocie** → sprawdzić `idx=0` w `practice.xml` vs config scr_server.

## Faza 1 — Manualny tuning baseline *(M, 2-4h, conditional)*

**Cel:** kontroler **kończy** okrążenie z dowolnym czasem (DNF zaszumiają TPE).

Tylko jeśli Faza 0 = DNF:
1. Z `telemetry.csv` zlokalizować punkt wypadku (SpeedX, TrackPos, DistRaced).
2. Iteracja (3-5×):
   - Wylot na szybkim łuku → ↓ `TARGET_STRAIGHT_SPEED` 290→260.
   - Wylot w szykanie → ↓ `MIN_NORMAL_CORNER_SPEED` 110→95, ↓ `BRAKE_THRESHOLD` 0.3→0.2.
   - Wężykowanie → ↓ `STEER_GAIN` 30→22.
3. Cel: 3 ukończone okrążenia z rzędu, czas obojętny.

**Deliverable:** `params_baseline.json` – staje się **centrum search-space dla Optuny**.

## Faza 2 — Smoke Optuna *(S, 30 min)*

**Cel:** end-to-end pipeline działa zanim zostawimy na noc.

1. `n_trials=500` → `n_trials=20`.
2. Zawęzić zakresy w `objective` do ±20% wokół `params_baseline` (zamiast szerokich z `optimize.py:73-81`).
3. Odpalić, mierzyć trials/min, % DNF, trend `study.best_value`.
4. **Gate:** best_of_20 ≤ baseline. Jak nie – obj_func ma bug, debug.

**Deliverable:** stats: trials/h → ETA pełnego runu.

## Faza 3 — Pełna Optuna na noc *(S setup, L wallclock 6-10h)*

**Cel:** zbiec do ≤1:30 lub blisko.

1. `n_trials` 250–500 zależnie od ETA z Fazy 2.
2. **Persistent storage:**
   ```python
   study = optuna.create_study(
       direction="minimize",
       storage="sqlite:///optuna_corkscrew.db",
       study_name="car1ow1_v1",
       load_if_exists=True,
   )
   ```
   Ctrl+C nie traci postępu, kontynuacja przez ponowne uruchomienie skryptu.
3. **Pruner** dla DNF/wolnych: `MedianPruner(n_startup_trials=15)` + `trial.report` w obj.
4. Odpalić, zostawić na noc na maszynie z aktywnym fokusem TORCS.
5. (opcj.) `optuna-dashboard sqlite:///optuna_corkscrew.db` w drugim oknie.

**Decision gate po nocy:**

| best_value      | dalej                                |
|-----------------|--------------------------------------|
| ≤ 1:30          | **TARGET HIT** → Faza 4 (walidacja)  |
| 1:30 < x ≤ 1:35 | Faza 4 + Faza 5 (refine)             |
| > 1:35          | Faza 6 (debug)                       |

## Faza 4 — Walidacja *(M, 1h)*

**Cel:** best_value to nie outlier z lucky seeda.

1. Oddzielny `validate.py` (kopia `optimize.py` bez Optuny i bez 128× speed).
2. 5 okrążeń, 1× sim speed, telemetria pełna.
3. Statystyki: `min ≤ best_value`, `mean ≤ best_value+2s`, std rozsądne.
4. Z `telemetry.csv` ręczna inspekcja – czy nie wykorzystuje glitcha (cięcie po piasku, kontakt z bandą jako "trail braking").

**Deliverable:** `lap_time_validated`, decyzja accept/refine.

## Faza 5 — Refinement *(opcjonalna, M-L, 4-8h)*

Eskalacja od najtańszej:

1. **Druga Optuna ±5% wokół params.json**, 200 trials – TPE local search.
2. **Rozszerzyć search-space** w `my_racer.py` – wyciągnąć z hardkodów do PARAMS:
   - Progi `corner_vision` (130/90/60/35).
   - `BRAKE_DISTANCE_GAIN_LINEAR` (0.35), `_QUADRATIC` (1200).
   - `TRAIL_BRAKE_FORGIVENESS_DIVISOR` (40.0).
   - ~12 params zamiast 8, nowa pełna Optuna.
3. **Per-segment params** – `get_track_params(distFromStart)` z osobnymi wartościami dla T1/T6/szykany. Optymalizować segment-wise.

## Faza 6 — Push poniżej 1:29 (rozszerzony search-space) *(L, 2-3 noce)*

> **Stan wejściowy (start Fazy 6):** best **89.24 s = 1:29.24** (Faza 5 + walidacja 4b),
> 7-param Optuna nasycona, `params_extended_best.json` jest snapshotem.
> **Cel Fazy 6:** zbicie 0.5–1.5 s przez tuning hardkodów w `my_racer.py`,
> których Optuna nigdy nie dotknęła.

### Hipoteza
W `my_racer.py` siedzi 9 hardkodów wąskiego gardła:

| # | Hardkod                                           | Lokalizacja               | Obecna  | Search range  |
|---|---------------------------------------------------|---------------------------|---------|---------------|
| 1 | `corner_vision > 130` (próg długiej prostej)      | my_racer.py:84            | 130.0   | 100–160       |
| 2 | `corner_vision > 90` → 240 km/h                   | my_racer.py:87-89         | 90/240  | 70–110/200–270|
| 3 | `corner_vision > 60` → 190 km/h                   | my_racer.py:90-92         | 60/190  | 45–80/150–230 |
| 4 | `corner_vision > 35` (próg ostrego zakrętu)       | my_racer.py:93            | 35.0    | 25–50         |
| 5 | `BRAKE_DISTANCE_LIN` (`speedX*0.35`)              | my_racer.py:138           | 0.35    | 0.20–0.55     |
| 6 | `BRAKE_DISTANCE_QUAD` (`speedX²/1200`)            | my_racer.py:138           | 1200    | 800–2000      |
| 7 | `TRAIL_BRAKE_DIVISOR` (`exit_vision/40`)          | my_racer.py:143           | 40.0    | 20–80         |
| 8 | `BRAKE_PRESS_DIVISOR` (`/(45*forgiveness)`)       | my_racer.py:144           | 45.0    | 25–80         |
| 9 | `is_corner` próg widzenia                         | my_racer.py:42            | 140.0   | 100–180       |

Największy oczekiwany zysk: **model hamowania (5–8)** — `v²/1200` był wymyślony bez optymalizacji,
a dohamowywanie to ~25% straty czasu na Corkscrew.

---

### Faza 6a — Brake-model tuning *(PRIORYTET, 1 noc, gain ~0.4–1.0 s)*

**Strategia:** zamrozić 7 parametrów z Fazy 5 (params_extended_best), tunować tylko 4 nowe parametry hamowania.
Mały search-space → szybka konwergencja, niskie ryzyko regresji apexów.

**Kroki implementacyjne (dla przyszłej sesji):**

1. **Modyfikacja `my_racer.py`** — wyciągnąć 4 hardkody z `apply_brakes` do PARAMS:
   ```python
   PARAMS = {
       # ... 7 starych ...
       "BRAKE_DISTANCE_LIN": 0.35,        # my_racer.py:138, dotychczas hardkod
       "BRAKE_DISTANCE_QUAD": 1200.0,     # my_racer.py:138, dotychczas hardkod
       "TRAIL_BRAKE_DIVISOR": 40.0,       # my_racer.py:143, dotychczas hardkod
       "BRAKE_PRESS_DIVISOR": 45.0,       # my_racer.py:144, dotychczas hardkod
   }
   ```
   Podmienić ciała w `apply_brakes`:
   ```python
   safe_distance = (S['speedX'] * PARAMS["BRAKE_DISTANCE_LIN"]) + (S['speedX'] ** 2) / PARAMS["BRAKE_DISTANCE_QUAD"]
   safe_distance = min(130.0, safe_distance)
   if front_path < safe_distance:
       forgiveness = max(1.0, exit_vision / PARAMS["TRAIL_BRAKE_DIVISOR"])
       brake += min(1.0, (safe_distance - front_path) / (PARAMS["BRAKE_PRESS_DIVISOR"] * forgiveness))
   ```

2. **Modyfikacja `optimize.py`** — nowy tryb `BRAKES=1`:
   - Przy starcie: `params = json.load(open("params_extended_best.json"))` (7 starych zafrozonych).
   - 4 nowe parametry przez `trial.suggest_float`:
     ```python
     params["BRAKE_DISTANCE_LIN"]  = trial.suggest_float("BRAKE_DISTANCE_LIN",  0.20, 0.55)
     params["BRAKE_DISTANCE_QUAD"] = trial.suggest_float("BRAKE_DISTANCE_QUAD", 800, 2000)
     params["TRAIL_BRAKE_DIVISOR"] = trial.suggest_float("TRAIL_BRAKE_DIVISOR", 20.0, 80.0)
     params["BRAKE_PRESS_DIVISOR"] = trial.suggest_float("BRAKE_PRESS_DIVISOR", 25.0, 80.0)
     ```
   - `STUDY_NAME` default = `"car1ow1_v3_brakes"`, fresh study (TPE od zera dla nowego search-space).
   - `N_TRIALS` default = 200 (małe pole, ~3-4 h).

3. **Sanity check** — odpalić `python startup.py` raz po modyfikacji `my_racer.py` z dotychczasowymi
   hardkodami zapisanymi jako defaulty PARAMS. Powinno dać **89.24 s ±0.1**. Jeśli nie — bug w refaktorze.

4. **Snapshot** — przed startem Optuny:
   ```bash
   cp params.json params_pre_faza6a.json
   ```

5. **Run:** `$env:BRAKES="1"; python optimize.py` (overnight ~3-4 h).

6. **Walidacja:** 5×1× speed (Faza 4-style). Akceptacja: `min ≤ best_value + 0.5`, `0 DNF` w 5 próbach.

7. **Zapis:** `params_brakes_best.json` (snapshot), `params.json` (aktywny), aktualizacja PLAN.md.

**Decision gate:**
- gain ≥ 0.5 s → kontynuuj Faza 6b.
- gain 0.2–0.5 s → idź od razu w Faza 6c (joint refit).
- gain ≤ 0.2 s → brake-model nasycony, idź Faza 6b.

---

### Faza 6b-rev — Brake-bounds extended *(NEW PRIORITY po 6a, ~3-4h, gain ~0.3-0.8s)*

**Powod zmiany kolejnosci:** w Fazie 6a 3 z 4 brake-params trafilo na floor:
- `BRAKE_DISTANCE_LIN = 0.217` (floor 0.20)
- `BRAKE_DISTANCE_QUAD = 826` (floor 800)
- `BRAKE_PRESS_DIVISOR = 28.0` (floor 25)

Floor byl arbitralny -> rozszerzamy w DOL zanim ruszamy w 6b-vision/6c-joint, bo:
- `v^2/500` zamiast `v^2/1200` -> jeszcze pozniejsze hamowanie na prostych,
- `safe = v*0.10 + v^2/500` -> agresywniejszy late-trail braking,
- `BRAKE_PRESS_DIVISOR=15` -> mocniej wcisnij gdy juz hamujesz.

**Tryb:** `BRAKES_EXT=1`, study `car1ow1_v3b_brakes_ext` (fresh, TPE od zera dla nowych granic), 200 trials.

**Bounds:**
| Param                  | Bylo (6a)     | Jest (6b-rev)  | Powod                          |
|------------------------|---------------|----------------|--------------------------------|
| BRAKE_DISTANCE_LIN     | 0.20-0.55     | 0.10-0.30      | floor 0.20 byl wiazacy         |
| BRAKE_DISTANCE_QUAD    | 800-2000      | 500-1200       | floor 800 byl wiazacy          |
| TRAIL_BRAKE_DIVISOR    | 20-80         | 25-60          | sweet spot ~40, zwezenie       |
| BRAKE_PRESS_DIVISOR    | 25-80         | 15-45          | floor 25 byl wiazacy           |

**Ryzyko:** DNF rate moze wzrosnac z 56% do 70%+ (jeszcze agresywniejsze hamowanie). Mitygacja: monitor po 30 trials,
jak best_value < 86.5 mozna ucinac wczesnie.

**Decision gate po 6b-rev:**
- gain >= 0.5 s -> Faza 6c (joint refit z brake-bounds rozszerzonymi).
- gain 0.2-0.5 s -> Faza 6b-vision dla niezaleznych +0.2s, potem 6c.
- gain <= 0.2 s -> brake-model nasycony, idz w 6b-vision.

### Faza 6b-vision — Vision thresholds *(po 6b-rev, 1 noc, gain ~0.2-0.5 s)*

Tunować 5 progów widzenia/prędkości w `calculate_throttle`. Brake-params i 7 starych zafrozić.

- Wyciąć z hardkodów (`my_racer.py:84-94`): `VISION_LONG_STRAIGHT` (130), `VISION_FAST_CORNER` (90),
  `SPEED_FAST_CORNER` (240), `VISION_MED_CORNER` (60), `SPEED_MED_CORNER` (190), opcjonalnie `VISION_TIGHT` (35).
- Tryb `optimize.py`: `VISION=1`, study `car1ow1_v4_vision`, 200 trials.
- Bound order constraint: `VISION_TIGHT < VISION_MED < VISION_FAST < VISION_LONG`
  (sprawdzić w `objective` po `suggest_float` i `return float("inf")` jak invalid — TPE się tego nauczy).
- Walidacja jak 6a.

### Faza 6c — Joint refit *(NEXT po 6b-vision walidacji, overnight, gain ~0.2–0.5 s)*

> **Stan wejsciowy:** best **86.03 s = 1:26.03** (Faza 6b-vision + walidacja 5/5),
> 16-param `params_vision_best.json` snapshotem. 2 nasycenia z 6b-vision do rozszerzenia.

**Strategia:** zamiast frozen-N tunowac wszystko 16 params **jednoczesnie** w waskim ±10% wokol obecnego best.
Cel: wylapac **efekty krzyzowe** (np. agresywniejsze hamowanie + wyzszy `SPEED_MED_CORNER` razem; albo
mniejszy `STEER_GAIN` + wyzszy `APEX_SHIFT_GAIN`). Te interakcje sa niewidoczne w frozen-mode, gdzie tunujemy 4-5
params na raz.

**2 nasycenia z 6b-vision rozszerzone (a nie ±10%):**
| Param              | Wartosc 6b-vis | Granice 6b-vis | Granice 6c              | Powod                 |
|--------------------|----------------|----------------|-------------------------|-----------------------|
| SPEED_FAST_CORNER  | 269.7          | 200-270        | **250-310**             | trafil ceiling 270    |
| VISION_MED_CORNER  | 46.2           | 45-80          | **25-60**               | trafil floor 45       |

**14 pozostalych params: ±10% wokol params_vision_best.** Constraint orderingu vision: `VISION_MED < VISION_FAST < VISION_LONG`
(prune jak naruszone, jak w 6b-vision).

**Implementacja w `optimize.py`:**
- Nowy tryb `JOINT=1`, study `car1ow1_v5_joint` (fresh, TPE od zera dla nowego search-space).
- `default_frozen = "params_vision_best.json"` ale w `JOINT` traktowany jako **centrum** (nie zafrozowane,
  tylko punkt referencyjny dla bounds).
- `N_TRIALS=200`, ~3-4h overnight.

**Sanity check:** zbedny — current params.json **=** params_vision_best.json (snapshot), my_racer.py niezmieniony
od 6b-vision walidacji. Bezposrednio robimy snapshot + run.

**Decision gate:**
- gain >= 0.5 s -> Faza 7-antislalom (1:25.5 lub mniej, slalom byl wciaz limitujacy).
- gain 0.2-0.5 s -> Faza 7-antislalom (joint nasycony, slalom wciaz krade czas).
- gain < 0.2 s -> Faza 7-antislalom moze dac wieksze zyski niz dalsze tuninge param-only.
- regresja -> rollback `cp params_pre_faza6c.json params.json`, wrocic do 86.03s.

---

### Faza 7-antislalom — Smooth apex shift *(po 6c, gain ~0.2-0.5s)*

> **Hipoteza:** wezykowanie obserwowane w walidacji 6b-vision (komunikat uzytkownika 2026-04-26) wynika z **bang-bang**
> apex shifta: w [my_racer.py:74-78](../my_racer.py#L74-L78) `bias = right_avg - left_avg` przekracza 0 i kierownica
> skacze ±0.46 (`APEX_SHIFT_GAIN`). Na odcinkach symetrycznych (S-ki, wyjscie z luku do prostej) bias szumi wokol zera
> -> sprzezenie zwrotne kierownica → trackPos → bias → kierownica daje oscylacje. Tracone czas: szacunek 0.2-0.5s/lap
> (utrata predkosci na slalomie + odsterowywanie).

**Fix B - smooth apex (tanh):**
```python
# zamiast:
if bias < 0: steer += APEX_SHIFT_GAIN
elif bias > 0: steer -= APEX_SHIFT_GAIN

# dac:
import math
steer -= APEX_SHIFT_GAIN * math.tanh(bias / APEX_SCALE)
```
- `tanh(bias / APEX_SCALE)` zwraca ~0 dla `|bias| << APEX_SCALE` (mala asymetria -> brak shiftu),
  saturuje do ±1 dla `|bias| >> APEX_SCALE` (duza asymetria -> pelny shift jak dotychczas).
- Eliminuje skok-od-zera, zachowuje zachowanie w wyraznych zakretach.
- Nowy hiperparametr: `APEX_SCALE` (np. 5-50, sweet spot pewnie ~20).

**Implementacja:**
1. Refaktor `calculate_steering` w `my_racer.py` (linie 74-78), nowy PARAM `APEX_SCALE` z defaultem ~20.
2. Sanity check: 5x1x speed z `params.json` z Fazy 6c, defaultem `APEX_SCALE=20.0` -> oczekiwane ~obecny best ±0.1s.
   Jak regresja - bug w refaktorze.
3. Optuna `ANTISLALOM=1`, study `car1ow1_v6_antislalom`. Tunowane TYLKO `APEX_SCALE` (1 param) + opcjonalnie
   `APEX_SHIFT_GAIN` (re-tuning bo zmiana skali shifta moze wymagac silniejszej amplitudy). 100 trials wystarczy.
4. Walidacja 5x1x, decision gate jak w 6c.

**Alternative fixes (do rozwazenia jak B nie pomoze):**
- Fix A (dead zone): `if abs(bias) > APEX_DEAD_ZONE: ...` - prostszy, mniej elegancki, gorszy w glebokich zakretach.
- Fix C (steering rate limit): `steer = clamp(steer, prev_steer-RATE, prev_steer+RATE)` - ortogonalny do A/B, mozna
  nalozyc jako Faza 7c dla synergii.

**Ryzyko:** smooth apex moze osłabic `agresywne wchodzenie w zakret` (komentarz w my_racer.py:74). Mitygacja: jak best
po 7-anti rosnie, znaczy ze APEX_SCALE jest za duze - Optuna sama zaweza.

---

### Realistyczny budżet
- **Sumaryczny gain 6a+6b+6c: 0.7–1.8 s** → cel **1:27.5–1:28.5**.
- Pesymistycznie 0.3 s → 1:28.9. Poniżej 1:27 wymaga zmian strukturalnych
  (PID na kąt, lookup-table per zakręt, model gum) — to już Faza 7.

### Ryzyka Fazy 6
| Ryzyko                                         | P | Mitygacja                                              |
|------------------------------------------------|---|--------------------------------------------------------|
| Refaktor `my_racer.py` zmienia zachowanie     | M | Sanity check w kroku 3 — best_value musi być ≈89.24    |
| Wzrost DNF rate od agresywnych hamowań        | M | Bounds startują konserwatywnie, MedianPruner           |
| Overfit do seed/lapa                           | M | Walidacja 5×1× po każdej sub-fazie                     |
| Drift vs `params_extended_best.json`           | L | Snapshot przed każdą sub-fazą                          |

## Faza 6-stara — Debug *(archiwum, gdyby >1:35)*

> **Nieaktualne** — TARGET 1:30 osiągnięty w Fazie 5. Zostawione na wypadek regresji.

Lista hipotez i fixów:
- **TPE utknęło w "DNF z największym dist"** (`return 10000-dist` zbyt łagodne) → zmiana obj: `return baseline_lap + 30` jak DNF.
- **Apex shift wariuje na low-speed apex w F1-aero** → warunek `if S['speedX'] < 80: bias=0`.
- **Hamowanie zbyt agresywne** (telemetria pokaże jeśli SpeedX leci poniżej target_speed na wejściu) → `v²/1200` → `v²/1500`.
- **TCS dusi exit** → `slip TCS` aktywny tylko `if S['speedX'] > 120`.

## Faza 7 — RL fallback *(L, 3-5 dni, opcjonalna)*

Tylko jeśli Optuna zatrzymuje się ~1:32-1:35 i chcemy pchnąć dalej. **Wracamy do Think repo:**
- `my_racer.drive_modular` jako nowy `expert_driver` (z hamowaniem, biegami, TCS).
- Nagrać 30+ epizodów `record_demos.py`.
- `warmstart_sac.py` jak poprzednio, ale bootstrap od **kompetentnego** demo.
- Oczekiwanie: SAC dotnie 0.5–2s wymyślając linie poza heurystyką.

---

## Risk Register

| Ryzyko                                                      | P     | Wpływ                | Mitygacja                                          |
|-------------------------------------------------------------|-------|----------------------|----------------------------------------------------|
| TORCS crash przy 128×                                       | H     | przerywa noc         | try/except w `run_torcs`, retry, sqlite storage    |
| PyAutoGUI traci fokus                                       | M     | sypie epizody        | dedykowana maszyna, żaden popup OS w nocy          |
| Best params overfit do seeda                                | M     | walidacja gorsza     | Faza 4 mandatory, 5 okrążeń                        |
| Sufit car1-ow1 + heurystyka ~1:33                           | M     | nie dotykamy 1:30    | Faza 5 (extended search-space) → Faza 7            |
| TPE w lokalnym DNF-min.                                     | M     | best_value fake      | monitor wcześnie, hard penalty fix                 |
| `torcs/` >100 MB w git                                      | L     | push fail            | LFS dla binarek (nie dotyczy nas: max plik <20MB)  |

## Complexity

- **Krytyczna ścieżka (Fazy 0–4):** 8–12h wallclock (z czego 6–10h Optuna w nocy).
- **Refinement (5–6):** +4–12h conditional.
- **RL fallback (7):** +3–5 dni, opcjonalna.

---

## Status fazowy (live)

| Faza | Stan       | Uwagi                                                                          |
|------|------------|--------------------------------------------------------------------------------|
| 0.1  | done       | commit 9dda8c0, torcs/ w repo, .gitignore zaktualizowane                       |
| 0.2  | done       | Corkscrew w obu practice.xml (root + torcs/config/raceman)                     |
| 0.3  | done       | scr_server slot 0 ma `car1-ow1`                                                |
| 0.4  | done       | baseline 1:37.47 x 4/5, 1 DNF (spin w T11). PARAMS=defaults wystarczajace      |
| 1    | skipped    | baseline konczy okrazenia, manualny tuning niepotrzebny                        |
| 2    | done       | 20/20 ukonczone, 0 DNF, best=95.486s = **1:35.49** (-2s vs baseline)           |
| 3    | done       | 460/500 lap-finishing, 8% DNF, best=**90.858s = 1:30.86** (trial #407)         |
| 4    | done       | 5 okrazen 1x: min=90.848, mean=91.92, 4/5 deterministyczne, 1 spin w T11       |
| 5    | done       | 285/500 lap-finishing, 43% DNF, best=**89.258s = 1:29.26** (-1.6s vs Faza 3)   |
| 4b   | done       | 5/5 = **89.24 s = 1:29.24** deterministycznie, 0 DNF, 0 outliers - **TARGET HIT** |
| 6a   | done       | Optuna 200 trials, best=87.340 s, walidacja **5/5=87.33 s = 1:27.33** ✓ 0 DNF   |
| 6b   | pending    | vision thresholds (5 params, study `car1ow1_v4_vision`)                        |
| 6b-rev| done      | Optuna 200, walidacja **5/5=86.67 s = 1:26.67** 0 DNF (best Optuny=86.69)     |
| 6b-vis| done-opt  | Optuna 200 trials, **best=86.002 s = 1:26.00** (-0.67s, 53.5% DNF, mean 87.03) |
| 6b-vis-w| done    | walidacja **5/5 = 86.03 s avg** (86.05/86.05/85.99/86.05/86.05), 0 DNF, spread 0.06s |
| 6c   | **next**   | JOINT mode, 16 params jednoczesnie, ±10% wokol best + 2 nasycenia rozszerzone  |
| 7-anti| pending   | smooth apex (tanh) anti-slalom, fix wezykowania na S-kach z bias≈0             |
| 7    | pending    | RL fallback (my_racer-as-expert + SAC), tylko jeśli 6c+7-anti nie odbije <1:25 |

## Wyniki kluczowe

- **Baseline (PARAMS=defaults z `params_baseline.json`):** 97.47 s = **1:37.47** na Corkscrew, car1-ow1.
  - 4/5 czystych okrazen, 1 DNF (spin w T11 ~2920 m, prawdopodobnie hairpin).
- **Faza 2 SMOKE (20 trials, +/-20% wokol baseline):** best **95.486 s = 1:35.49** (-2.0s vs baseline).
  - 20/20 ukonczone, 0 DNF -> waskie okno bezpieczne ale ograniczajace.
  - TARGET_STRAIGHT_SPEED i MIN_NORMAL_CORNER_SPEED uderzyly w gorna granice okna -> w pelnym search-space jest jeszcze zapas.
- **Faza 3 FULL (500 trials, full search-space):** best **90.858 s = 1:30.86** (trial #407).
  - 460/500 lap-finishing, 8% DNF rate.
  - Saturacja granic: STEER_GAIN floor (15.01), CENTERING_GAIN floor (0.056), MIN_NORMAL_CORNER_SPEED ceiling (146.6/150).
  - Best params: TARGET=296.82, SAFE_SHARP=52.50, MIN_CORNER=146.60, STEER=15.01, CENTER=0.056, BRAKE=0.272, APEX=0.544.
  - Zapisane w `params_full_best.json` jako fallback.
- **Faza 4 walidacja (5 okrazen 1x speed):** min=**90.848 s = 1:30.85**, mean=91.92, std=2.13.
  - 4/5 deterministyczne, 1 outlier 96.19 (spin w T11 - ta sama stochastyka co pre-Optuna).
- **0.85 sekundy do targetu 1:30** po Fazie 4.
- **Faza 5 EXTENDED (500 trials, rozszerzone granice):** best **89.258 s = 1:29.26** -> **TARGET HIT** (-1.6s vs Faza 3, -8.21s vs baseline).
  - 285/500 lap-finishing, 43% DNF rate (cena agresywnych granic, ale TPE i tak znalazl szybsze geny).
  - Best params: TARGET=279.74, SAFE_SHARP=83.74, MIN_CORNER=117.48, STEER=5.10, CENTER=0.048, BRAKE=0.273, APEX=0.454.
  - SAFE_SHARP_CORNER_SPEED skoczyl 52.5->83.74 (kontroler ufa szerszemu apexowi), STEER_GAIN spadl do nowego floor (5.10) - spokojniejszy gas/odsterowanie.
  - Zapisane w `params_extended_best.json` (i `params.json` jako aktywny).
  - Walidacja Faza 4b (5 okrazen 1x): **5/5 = 89.24 s = 1:29.24, 0 DNF, 0 outliers** - bardziej stabilne niz Faza 4 (tam 1 spin w T11).
- **TARGET 1:30 OSIAGNIETY z zapasem 0.76 s**, 0 DNF, deterministycznie.
- **Faza 6a BRAKES (200 trials, brake-model tuning, 7 frozen):** best **87.340 s = 1:27.34** -> -1.9s vs Faza 5.
  - 87/200 lap-finishing, 56% DNF rate (cena agresywnych brake-bounds, ale TPE wycial szybsze geny).
  - Best params (4): BRAKE_DISTANCE_LIN=0.217 (floor 0.20), BRAKE_DISTANCE_QUAD=826.0 (floor 800), TRAIL_BRAKE_DIVISOR=40.4 (default ~40), BRAKE_PRESS_DIVISOR=28.0 (floor 25).
  - 3/4 params na floor -> brake-model nasycony, ale dolne granice trzeba poszerzyc w Fazie 6c.
  - Kierunek: pozniejsze hamowanie (mniejszy LIN+QUAD safe_distance) + mocniejsze wcisniecie (mniejszy PRESS_DIVISOR) = late-trail braking.
  - Zapisane w `params_brakes_best.json` (tylko 4 nowe) i `params.json` (merge 7+4=11).
  - **Walidacja Faza 6a (5x1x): 5/5 = 87.33 s = 1:27.33** deterministycznie, 0 DNF, 0 outliers - bardziej stabilne niz pre-6a (5/5 = 89.24, tez 0 DNF; tu rozjazd -1.91s).
- **Bug fix Faza 6a:** `optimize.py` w trybie `BRAKES` zapisywal tylko 4 zasugerowane params do `params.json`, gubiac 7 zafrozonych. Naprawione przez merge `{**FROZEN_PARAMS, **study.best_params}` przed dump.
- **Faza 6b-vision VISION (200 trials, 11 zafrozonych + 5 vision-params):** best **86.002 s = 1:26.00** -> -0.67s vs 6b-rev, lacznie -11.45s vs baseline.
  - 93/200 lap-finishing, 53.5% DNF rate (lekko stabilniej niz 6b-rev), mean treningu 87.03 (vs 6b-rev 88.78 = polepszylo o 1.75s).
  - Best params: VISION_LONG_STRAIGHT=127.5 (≈default 130), VISION_FAST_CORNER=103.0 (wzrost +13), VISION_MED_CORNER=46.2 (FLOOR 45), SPEED_FAST_CORNER=269.7 (CEILING 270), SPEED_MED_CORNER=213.7 (wzrost).
  - Wniosek: agresywne klasyfikowanie lukow jako fast i wciskanie 270 km/h. Medium-corner band niemal wyciety (floor 45) - na Corkscrew sa albo szybkie luki, albo szykany.
  - 2 nasycenia: SPEED_FAST_CORNER (ceiling 270) i VISION_MED_CORNER (floor 45) -> Faza 6c rozszerzy.
  - Zapisane w `params_vision_best.json` i `params.json` (merge 11+5=16).
- **Faza 6b-rev BRAKES_EXT (200 trials, rozszerzone DOLNE brake-bounds):** best **86.686 s = 1:26.69** -> -0.65s vs 6a, lacznie -10.78s vs baseline.
  - 91/200 lap-finishing, 54% DNF rate (lekko stabilniej niz 6a 56%, mean 88.78 vs 6a 91.64 = treningowy mean polepszyl sie o 2.9s).
  - Best params (4): BRAKE_DISTANCE_LIN=0.224 (NIE floor), BRAKE_DISTANCE_QUAD=1025 (wzrost!), TRAIL_BRAKE_DIVISOR=49.5 (wzrost), BRAKE_PRESS_DIVISOR=17.5 (blisko floor 15).
  - Tylko BRAKE_PRESS_DIVISOR uderzyl floor - inne params konwergowaly w "innej okolicy" niz 6a, sygnal ze brake-model jest praktycznie nasycony.
  - Styl: pozniej zacznij hamowac (LIN/QUAD podobne lub luzniejsze), ale jak juz hamujesz to mocno (PRESS_DIVISOR 17.5), i wiecej forgiveness na exit (TRAIL_DIVISOR 49.5).
  - Zapisane w `params_brakes_ext_best.json` i `params.json` (merge 7+4=11 dzialal poprawnie po fixie).
- **Faza 6b-vision walidacja (5x1x, 2026-04-26):** **5/5 = 86.03 s avg** (86.05/86.05/85.99/86.05/86.05), 0 DNF, spread 0.06s.
  - **NOWY BASELINE: 1:26.03**, total gain od baseline: -11.44s, gain od Fazy 5 walidacji: -3.21s.
  - Determinizm bardzo wysoki (4/5 to dokladnie 86.05) -> Optuna best 86.00 jest nieco optymistyczny vs realny 86.03,
    ale spread 0.06s jest super.
  - **Obserwacja uzytkownika:** w niektorych powtarzalnych miejscach toru bot robi slalomy. Hipoteza: bang-bang
    apex shift na bias≈0 -> Faza 7-antislalom.
- **Faza 6c JOINT (planowana, 200 trials, 16 params):** ±10% wokol params_vision_best, 2 nasycenia rozszerzone
  (SPEED_FAST_CORNER 250-310, VISION_MED_CORNER 25-60). Cel: efekty krzyzowe niewidoczne we frozen-mode.

## Komendy

```powershell
# Faza 2 - smoke Optuna (20 prob, +/-20% wokol baseline)
$env:SMOKE = "1"
python optimize.py

# Faza 3 - pelna Optuna (500 prob, pelny search-space)
$env:SMOKE = "0"
python optimize.py

# Faza 5 - EXTENDED Optuna (rozszerzone nasycone granice, 500 prob, fresh study car1ow1_v2)
Remove-Item Env:SMOKE -ErrorAction SilentlyContinue
$env:EXTENDED = "1"
python optimize.py

# Faza 6a - Brake-model tuning (4 nowe params, 7 starych zafrozonych, 200 trials, study car1ow1_v3_brakes)
Remove-Item Env:SMOKE,Env:EXTENDED -ErrorAction SilentlyContinue
$env:BRAKES = "1"
python optimize.py

# Faza 6b-rev - Brake-bounds rozszerzone w dol (3/4 trafilo floor w 6a, fresh study car1ow1_v3b_brakes_ext)
Remove-Item Env:SMOKE,Env:EXTENDED,Env:BRAKES -ErrorAction SilentlyContinue
$env:BRAKES_EXT = "1"
python optimize.py

# Faza 6b-vision - Tunowanie 5 progow vision/speed (11 zafrozonych z 6b-rev, study car1ow1_v4_vision)
Remove-Item Env:SMOKE,Env:EXTENDED,Env:BRAKES,Env:BRAKES_EXT -ErrorAction SilentlyContinue
$env:VISION = "1"
python optimize.py

# Faza 6c - JOINT (16 params jednoczesnie, ±10% wokol params_vision_best, 2 nasycenia rozszerzone)
Remove-Item Env:SMOKE,Env:EXTENDED,Env:BRAKES,Env:BRAKES_EXT,Env:VISION -ErrorAction SilentlyContinue
$env:JOINT = "1"
python optimize.py

# Walidacja (Faza 4) - 5 okrazen 1x speed
# zmien STEPS=5 w startup.py i:
python startup.py

# Wznowienie po Ctrl+C - ta sama komenda, sqlite ladowane z load_if_exists=True
```

## Quick-resume cheatsheet (dla nowej sesji)

Jeśli zaczynasz świeżą sesję i widzisz tylko ten plik:

1. **Aktualny best:** 86.03 s = **1:26.03** (walidacja 6b-vision 5/5, 0 DNF, spread 0.06s).
   `params.json` = `params_vision_best.json` (snapshot, 16 keys).
2. **Co dalej:** Faza 6c JOINT - patrz sekcja "Faza 6c - Joint refit" wyzej.
3. **Pierwszy krok Fazy 6c:** snapshot zrobiony (`params_pre_faza6c.json`), tryb dodany w `optimize.py`.
   Wystarczy odpalic: `$env:JOINT="1"; python optimize.py`.
4. **Po 6c:** Faza 7-antislalom (smooth apex tanh) jezeli walidacja 6c przejdzie.
5. **Kluczowe pliki:** `params_vision_best.json` (centrum, 16), `params_pre_faza6c.json` (snapshot rollback),
   `my_racer.py` (BEZ zmian dla 6c, refaktor potrzebny dopiero w 7-antislalom),
   `optuna_corkscrew.db` (study `car1ow1_v5_joint` powstanie po starcie).

---

## Narrative log (notatki do filmiku/podsumowania)

> Sekcja chronologiczna z momentami, ktore warto opowiedziec w filmiku - problemy, decyzje, "aha moments".

### Akt 1: Pivot z RL na rule-based + Optuna (start sesji)
- **Punkt wyjscia:** drugie repo `IBM-TORCS-Think` z SAC + warmstart (gap-steering expert), 230k krokow treningu,
  ep_rew_mean dopiero zaczynal piac sie z 3 do 88. Realny ETA do sub-1:30: 1.5-3M krokow + reward shaping.
- **Decyzja:** porzucic dotychczasowy RL setup, zaczac drugie podejscie - reaktywny rule-based kontroler
  (heurystyki: lookahead steering, apex shifting, multi-tier target speed, trail braking, TCS)
  + Optuna do tuningu floatowych params. Asymetria: dni vs godziny.
- **Hook do filmiku:** "RL widzialo wzgorze, my poszlismy obejsc gora kolem".

### Akt 2: Pierwsza Optuna (Fazy 0-3, baseline → 1:30.86)
- Baseline z defaultami: 1:37.47, 4/5 czystych okrazen, 1 spin w T11.
- Faza 2 SMOKE (+/-20%): 1:35.49 w 20 trialach -> piepelina dziala, mozemy zostawic na noc.
- Faza 3 FULL (500 trials, 7 params): **1:30.86**, 92% lap-finishing.
- 3 parametry uderzaly w granice: STEER_GAIN floor (15.01), CENTERING_GAIN floor (0.056), MIN_NORMAL_CORNER_SPEED ceiling (146.6/150).
- **"Aha moment":** Optuna nie tylko stroi, ale **diagnozuje** waskie gardla architektonicznie - pokazuje, ze nasze
  intuicyjne granice byly za waskie.

### Akt 3: Extended bounds + TARGET HIT (Faza 5, 1:29.24)
- Rozszerzone granice na 3 nasycone params + 4 dodatkowe (CENTER 0.0-0.4, STEER 5-45, BRAKE_THRESHOLD 0.1-0.5, APEX 0.1-0.8).
- **1:29.26** Optuna best, walidacja 5/5 = 1:29.24 deterministycznie, 0 DNF.
- Cena: 43% DNF rate w treningu (TPE wyciagal szybsze geny mimo strat).
- **Insight:** "DNF jako sygnal" - reward `10000 - dist_raced` mowi TPE, ze "blisko-DNF" jest blizej rozwiazania niz
  "wolny i czysty". TPE balansuje ryzyko sam.

### Akt 4: Wyciaganie hardkodow z my_racer.py (Faza 6, 9 hipotez)
- TARGET 1:30 osiagniety, ale w `my_racer.py` siedzi jeszcze **9 hardkodow** ktorych Optuna nigdy nie dotknela:
  4 brake-params (`v*0.35 + v^2/1200`, `exit_vision/40`, `/(45*forgiveness)`),
  5 vision-params (130/90/240/60/190), oraz `is_corner` prog 140.
- Hipoteza: brake-model byl wymyslony bez optymalizacji - tu siedzi najwiekszy zapas.
- Strategia frozen-N: zamrazac N starych params, tunowac tylko K nowych. Mniejsza wymiarowosc -> szybsza konwergencja.

### Akt 5: Faza 6a (brake-tuning) - **bug fix** + 1.91s gain
- Refaktor 4 hardkodow do PARAMS, sanity check 5x = 89.24 (przeszedl).
- 200 trials, best=87.34s = **1:27.34**.
- **3 z 4 brake-params trafilo we floor** - granice byly arbitralnie konserwatywne.
- **CRITICAL BUG:** `study.best_params` w trybie BRAKES zwracal tylko 4 zasugerowane params, nie 7 zafrozonych ->
  `params.json` zostalby nadpisany 4 keys, walidacja uzylaby defaultow zamiast 7 zafrozonych z Fazy 5.
- **Fix:** `full_params = {**FROZEN_PARAMS, **study.best_params}` w optimize.py przed dump.
- **Hook do filmiku:** "Optuna nie wiedziala o tej zmiennej, my wiedzielismy o niej" - subtelny bug-class
  ktory pokazuje ze frozen-N wymaga eksplicytnego mergowania, nie samego Optuny.

### Akt 6: Faza 6b-rev (rozszerzone DOLNE brake-bounds) - 0.65s gain
- Skoro 3/4 trafilo floor, rozszerzylismy w dol (LIN 0.10-0.30, QUAD 500-1200, PRESS 15-45).
- Best=86.69s = **1:26.69**, walidacja 5/5 = 86.67.
- **Tym razem tylko 1 z 4 (BRAKE_PRESS_DIVISOR) blisko floor 15** - brake-model nasycony.
- Drugi rzut konwergowal w innej "okolicy" niz pierwszy - sygnal ze model ma kilka rownowaznych minimow.

### Akt 7: Faza 6b-vision (vision/speed thresholds) - 0.66s gain
- 5 vision params (LONG/FAST/MED prog, FAST/MED speed) + constraint orderingu (`MED < FAST < LONG`) przez `optuna.TrialPruned()`.
- Best=86.00s = **1:26.00** Optuna, walidacja 5/5 = **86.03 avg, spread 0.06s**, 0 DNF.
- 2 nasycenia: SPEED_FAST_CORNER 269.7 (ceiling 270), VISION_MED_CORNER 46.2 (floor 45).
- Bot stabilny do mlecza - od tej fazy walidacja jest niemal deterministyczna.
- **Total gain od baseline: -11.44s** (97.47 -> 86.03).

### Akt 8: Slalom-bug, Faza 6c JOINT (overfit) i Faza 7 ANTISLALOM (failure)
- Uzytkownik zauwazyl: bot robi slalomy w niektorych powtarzalnych miejscach toru.
- Diagnoza: bang-bang apex shift na `bias≈0` daje skok ±0.46 z chwila przejscia bias przez 0.
  Sprzezenie zwrotne kierownica → trackPos → bias powoduje oscylacje.

**Faza 6c JOINT (rownolegle przed antislalom)** — 200 trials, wszystkie 16 params ±10% wokol vision_best.
- Best @ 128x sim: **85.164s** (~1:25, lepszy niz vision_best 86.05).
- Walidacja 5x1x: **5/5 DNF** (zazwyczaj 2470.2m - najostrzejszy zakret).
- **Wnioski:** JOINT to overfit do fizyki 128x. Slalom @ 128x mial inne charakterystyki niz @ 1x,
  Optuna znalazla genom wykorzystujacy te roznice. 4 params trafilo lower bound (CENTERING_GAIN, APEX_SHIFT_GAIN,
  BRAKE_DISTANCE_LIN, BRAKE_PRESS_DIVISOR) -> "luzniej hamowac, mniej centrowac" = setup ktory dziala tylko
  przy mocno przyspieszonej fizyce. Snapshot zachowany jako `params_joint_best.json` (artefakt).
- **Hook do filmiku:** "Optuna znalazla 1:25... ktorego nie da sie zwalidowac".

**Faza 7 ANTISLALOM** — 100 trials, smooth tanh apex (refactor `my_racer.py`):
- Implementacja: `steer -= APEX_SHIFT_GAIN * tanh(bias / APEX_SCALE)`. Nowy param `APEX_SCALE` w `[0.05, 5.0]`.
  Default `APEX_SCALE=0.05` -> ~bang-bang dla typowych |bias|>0.15 (preserves baseline).
- Best @ 128x: 89.570s, **3/100 lap, 97 DNF**. Winner: `APEX_SHIFT_GAIN=0.4166, APEX_SCALE=2.106`.
- **Wniosek:** smooth tanh dampening dziala (APEX_SCALE wygral daleko od 0.05), ale kosztuje 3.5s/lap +
  fragility. Zatlumione mid-corner odbiera bota o agresywnosc apex - cena niewspolmierna do gainu.
- Snapshot zachowany jako `params_antislalom_best.json` (artefakt). Runtime rollback do vision_best.
- **Hook do filmiku:** "Niektore fixy strukturalne sa gorsze niz problem ktory naprawiaja".

### Akt 9: Faza 8 JOINT64 (overnight - eliminacja overfit)
- **Hipoteza:** JOINT 6c overfit zniknie jak zmniejszymy gap fizyki. Idea: ta sama logika optymalizacji
  (16 params, ±10% wokol vision_best, 2 nasycone rozszerzone), ale przy `SPEEDUP_PRESSES=6` (~32x)
  zamiast 8 (~128x). Trials zwalidowalne przy 1x.
- Implementacja: nowy MODE `JOINT64` w `optimize.py` + env var `SPEEDUP_PRESSES`. Study `car1ow1_v7_joint64`,
  250 trials default (~8-16h). Patrz `OVERNIGHT_RUN.md` po szczegoly.
- **Spodziewane wyniki:**
  - Optymistycznie: 84.5-85.5s lap @ 1x (1:24-1:25), beat 1:26 baseline o ~0.5-1.5s.
  - Pesymistycznie: znow overfit, lub konwergencja do okolic 86s (32x dalej za szybkie). Plan B w OVERNIGHT_RUN.md.
- Snapshoty bezpieczenstwa przed startem: `params_vision_best.json` (1:26 baseline) nietkniety,
  `optuna_corkscrew_backup_pre_joint64.db`, kopie pre-faza w params_pre_*.json.

### Lessons learned (do filmiku)
1. **Pivot szybko** - jak RL nie zbiega w rozsadnym czasie, sprobuj prostszego baseline.
2. **Frozen-N jako anti-overfit:** zamiast tunowac 16 params naraz (curse of dimensionality + DNF nosie ze sprawia ze
   TPE bias jest losowy), tunuj 4-5 na raz w warstwach. Faza 6c (joint) jest na koncu, nie na poczatku.
3. **Optuna jako diagnostyk granic:** jak param trafia we floor/ceiling, to nie tylko "trzeba rozszerzyc" ale
   "nasza intuicja byla zla, model jest podtuniony tutaj".
4. **DNF rate to nie blad - to sygnal:** 50%+ DNF znaczy ze TPE bedzie eksplorowal granice katastrofy gdzie sa
   najszybsze geny. Akceptujemy bo walidacja 5x1x weryfikuje stabilnosc.
5. **Bugs in scripts > bugs in racing logic:** `params.json` overwrite z 4 keys zamiast 11 zatrzymalby pelna sciezke
   eksperymentu. Mergowanie frozen+suggested musi byc eksplicytne.
6. **Snapshot przed kazda faza:** `params_pre_faza6X.json` to bilet powrotny. Bez tego rollback to dni roboty.
