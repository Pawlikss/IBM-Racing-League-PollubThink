import os
import time
import pyautogui
import subprocess
import sys

def start_torcs():
    print("[1/4] Closing previous TORCS instances...")
    os.system('taskkill /f /im wtorcs.exe >nul 2>&1')
    time.sleep(1.0)
    
    # Locate the TORCS game folder
    script_dir = os.path.dirname(os.path.abspath(__file__))
    torcs_dir = os.path.join(script_dir, "torcs")
    cwd = os.getcwd()
    
    if os.path.exists(torcs_dir):
        os.chdir(torcs_dir)
        print(f"[2/4] Launching TORCS from directory: {torcs_dir}")
    else:
        print("[2/4] Launching TORCS from current directory.")

    # Launch game without damage, fuel, and laptime limits
    os.system('start "" wtorcs.exe -nofuel -nodamage -nolaptime')
    
    print("Waiting 3 seconds for the game window to load...")
    time.sleep(3.0)
    
    print("[3/4] Automatically navigating menus...")
    # Sequence: Race -> Quick Race -> Accept -> Accept
    for key in ['enter', 'enter', 'enter', 'enter']:
        pyautogui.press(key)
        time.sleep(0.2)
        
    print("Game ready! Waiting 2 seconds for SCR server initialization...")
    time.sleep(2.0)
    os.chdir(cwd)

if __name__ == "__main__":
    STEPS = 5  # Phase 4 (validation) - 5 laps at 1x speed; restore to 3 for daily testing
    
    for x in range(STEPS):
        print(f"\n=== STARTING RACE {x+1} of {STEPS} ===")
        start_torcs()
        print("[4/4] Launching the bot (my_racer.py)...")
        try:
            subprocess.run([sys.executable, "my_racer.py"])
        except KeyboardInterrupt:
            print("\nRaces interrupted by the user.")
            break
        finally:
            print("Closing TORCS after the race...")
            os.system('taskkill /f /im wtorcs.exe >nul 2>&1')
            time.sleep(1.0)