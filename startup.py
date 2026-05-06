import os
import time
import pyautogui
import subprocess
import sys

def start_torcs():
    print("[1/4] Zamykanie poprzednich instancji TORCS...")
    os.system('taskkill /f /im wtorcs.exe >nul 2>&1')
    time.sleep(1.0)
    
    # Szukanie folderu gry TORCS
    script_dir = os.path.dirname(os.path.abspath(__file__))
    torcs_dir = os.path.join(script_dir, "torcs")
    cwd = os.getcwd()
    
    if os.path.exists(torcs_dir):
        os.chdir(torcs_dir)
        print(f"[2/4] Uruchamianie TORCS z katalogu: {torcs_dir}")
    else:
        print("[2/4] Uruchamianie TORCS z bieżącego katalogu.")

    # Uruchomienie gry w trybie bez uszkodzeń, paliwa i limitu czasu
    os.system('start "" wtorcs.exe -nofuel -nodamage -nolaptime')
    
    print("Czekam 3 sekundy na załadowanie okna gry...")
    time.sleep(3.0)
    
    print("[3/4] Automatyczne przeklikiwanie menu...")
    # Sekwencja: Race -> Quick Race -> Akceptuj -> Akceptuj
    for key in ['enter', 'enter', 'enter', 'enter']:
        pyautogui.press(key)
        time.sleep(0.2)
        
    print("Gra gotowa! Czekam 2 sekundy na inicjalizację serwera SCR...")
    time.sleep(2.0)
    os.chdir(cwd)

if __name__ == "__main__":
    STEPS = 5  # Faza 4 (walidacja) - 5 okrazen w 1x speed; przywroc do 3 dla codziennego testu
    
    for x in range(STEPS):
        print(f"\n=== ROZPOCZYNAM WYŚCIG {x+1} z {STEPS} ===")
        start_torcs()
        print("[4/4] Uruchamianie bota (my_racer.py)...")
        try:
            subprocess.run([sys.executable, "my_racer.py"])
        except KeyboardInterrupt:
            print("\nWyścigi przerwane przez użytkownika.")
            break
        finally:
            print("Zamykanie TORCS po wyścigu...")
            os.system('taskkill /f /im wtorcs.exe >nul 2>&1')
            time.sleep(1.0)