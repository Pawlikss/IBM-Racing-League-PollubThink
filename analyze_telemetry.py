import csv
import sys

def analyze():
    file_path = 'telemetry.csv'
    
    total_rows = 0
    max_speed = 0.0
    min_speed = 999.0
    speeds = []
    
    full_throttle_count = 0
    brake_count = 0
    off_track_count = 0
    
    corner_speeds = []
    straight_speeds = []
    
    lap_times = []
    max_lap_time = 0.0
    
    with open(file_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_rows += 1
            try:
                speed = float(row['SpeedX'])
                accel = float(row['Accel'])
                brake = float(row['Brake'])
                track_pos = float(row['TrackPos'])
                in_corner = row['InCorner'].strip().lower() == 'true'
                cur_lap_time = float(row['CurLapTime'])
                
                speeds.append(speed)
                if speed > max_speed: max_speed = speed
                if speed < min_speed: min_speed = speed
                
                if accel > 0.9: full_throttle_count += 1
                if brake > 0.1: brake_count += 1
                if abs(track_pos) > 1.0: off_track_count += 1
                
                if in_corner:
                    corner_speeds.append(speed)
                else:
                    straight_speeds.append(speed)
                    
                if cur_lap_time > max_lap_time:
                    max_lap_time = cur_lap_time
                elif cur_lap_time < max_lap_time - 10: # lap reset
                    lap_times.append(max_lap_time)
                    max_lap_time = cur_lap_time
                    
            except Exception as e:
                pass
                
    if max_lap_time > 0:
        lap_times.append(max_lap_time)

    avg_speed = sum(speeds) / len(speeds) if speeds else 0
    avg_corner_speed = sum(corner_speeds) / len(corner_speeds) if corner_speeds else 0
    avg_straight_speed = sum(straight_speeds) / len(straight_speeds) if straight_speeds else 0
    
    # Filtrowanie prawidłowych okrążeń - odrzucamy resety/bugi < 80 sekund
    valid_laps = [t for t in lap_times if t > 80.0]
    bugged_laps = [t for t in lap_times if t <= 80.0]

    print('--- RAPORT INZYNIERA WYSCIGOWEGO ---')
    print(f'Przeanalizowane probki: {total_rows}')
    print(f'Zarejestrowane okrazenia (Prawidlowe >80s): {len(valid_laps)} {[round(t, 2) for t in valid_laps]}')
    if valid_laps:
        print(f'Najlepszy czas: {min(valid_laps):.2f}s | Sredni czas: {sum(valid_laps)/len(valid_laps):.2f}s')
    print(f'Zarejestrowane bledy/wypadki (<80s): {len(bugged_laps)}')
    print(f'Predkosc Maksymalna: {max_speed:.2f} km/h')
    print(f'Srednia Predkosc: {avg_speed:.2f} km/h')
    print(f'Srednia Predkosc (Zakrety): {avg_corner_speed:.2f} km/h')
    print(f'Srednia Predkosc (Proste): {avg_straight_speed:.2f} km/h')
    print(f'Czas z gazem w podlodze (>90%): {(full_throttle_count/total_rows)*100:.1f}%')
    print(f'Czas na hamulcu (>10%): {(brake_count/total_rows)*100:.1f}%')
    print(f'Czas poza torem (TrackPos > 1 lub < -1): {(off_track_count/total_rows)*100:.1f}%')

analyze()
