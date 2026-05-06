# TORCS AI Racing Bot (Optuna + Dynamic Lines)

Ten projekt to zaawansowany, modularny bot wyścigowy do symulatora **TORCS** (The Open Racing Car Simulator). Oparty jest o infrastrukturę `gym_torcs` oraz architekturę klient-serwer (`snakeoil3`).

Zamiast sztywnych reguł (hardcoding), bot korzysta z **Optymalizacji Bayesowskiej** do poszukiwania idealnych parametrów wejść w zakręty oraz dynamicznie generuje **linie wyścigowe** (tzw. Apex Shifting).

## 📂 Najważniejsze pliki:

- `my_racer.py` - Główny "mózg" bota. Zawiera logikę czytania sensorów, dohamowywania i przyspieszania.
- `optimize.py` - Skrypt trenujący. Uruchamia silnik fizyki w trybie przyspieszonym (x128) i używa algorytmu TPE z biblioteki Optuna do szukania idealnych parametrów (np. marginesów dohamowywania).
- `startup.py` - Menedżer uruchamiania. Zabija wiszące procesy w tle, automatycznie nawiguje po menu gry i włącza bota.
- `logger.py` - System telemetrii zapisujący wyniki okrążeń do plików CSV.

## 🚀 Wymagania

- **Python 3.10+** (testowane na 3.14.3, ale 3.10/3.11/3.12 też powinny działać)
- **Windows** (TORCS dostarczony tu to wersja `wtorcs.exe`; PyAutoGUI używa Win API do wciskania klawiszy menu)
- biblioteki Pythona z `requirements.txt`

### Setup od zera (np. po `git clone` na nowej maszynie)

```powershell
git clone <repo-url>
cd IBM-TORCS-Think2

# (opcjonalnie) virtualenv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

TORCS engine (`torcs/wtorcs.exe` + tracki + samochody, ~520 MB) jest commitowany w repo,
więc po `git clone` wszystko jest gotowe — żadnej zewnętrznej instalacji TORCS-a nie trzeba.

> **UWAGA — pierwszy `git clone` zajmie kilka minut** ze względu na 520 MB engine'u TORCS.

## 🎮 Jak uruchomić?

### Opcja 1: Standardowy wyścig (Testowanie)

Aby zobaczyć bota w akcji na torze bez modyfikacji parametrów, wystarczy użyć skryptu startowego. Sam włączy grę i wciśnie odpowiednie klawisze w menu:

```bash
python startup.py
```

### Opcja 2: Proces Optymalizacji (Poszukiwanie czasów)

Aby puścić bota w tryb nauki, odpal moduł sztucznej inteligencji. Bot przejedzie zadaną ilość prób, samodzielnie restartując środowisko po każdym błędzie lub wypadku, dążąc do ucinania ułamków sekund z czasu okrążenia:

```powershell
# Pelny run (Faza 3 z PLAN.md) - 500 prob, ~8-12h, na noc
$env:SMOKE = "0"
python optimize.py

# Smoke run (Faza 2) - 20 prob, +/-20% wokol baseline, ~20-30 min
$env:SMOKE = "1"
python optimize.py
```

Najlepsze uzyskane geny trafią do pliku `params.json`, po czym `my_racer.py` automatycznie je wczyta podczas kolejnych jazd.

Postęp jest persistowany w `optuna_corkscrew.db` (SQLite) — Ctrl+C jest bezpieczne, ponowne odpalenie tego samego polecenia kontynuuje od ostatniej zakończonej próby (`load_if_exists=True`).

### Opcja 3: Podgląd statystyk istniejącego badania

```powershell
python inspect_study.py smoke_v1     # po Fazie 2
python inspect_study.py car1ow1_v1   # po Fazie 3
```

Pokaże ile prób zakończonych, ile DNF, top-5 czasów, best params.

---

**Note:** Architektura uwzględnia zabezpieczenia środowiska, które przy crashu wewnętrznego serwera gry (typowe dla bardzo szybkich obliczeń pod systemem Windows) same wymuszą restart instancji TORCS i wznowią trening.
