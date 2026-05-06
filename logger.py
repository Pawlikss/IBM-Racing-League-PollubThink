import os
import csv

class LogData:
    def __init__(self, path="recordings.csv"):
        self.path = path
        self.headers = [
            "TARGET_STRAIGHT_SPEED",
            "SAFE_CORNER_SPEED",
            "STEER_GAIN",
            "CENTERING_GAIN",
            "BRAKE_THRESHOLD",
            "LapTime",
            "DistRaced"
        ]

    def log_data(self, lap_run_data):
        # Sprawdza czy plik istnieje, żeby wiedzieć, czy dodać nagłówki
        file_exists = os.path.isfile(self.path)
        with open(self.path, "a", newline="") as file:
            writer = csv.writer(file)
            if not file_exists:
                writer.writerow(self.headers)
            writer.writerow(lap_run_data)

class TelemetryLogger:
    def __init__(self, path="telemetry.csv"):
        self.path = path
        # Nagłówki zapisywanych danych w trakcie jazdy
        self.headers = ["CurLapTime", "DistRaced", "SpeedX", "TrackPos", "Angle", "Steer", "Accel", "Brake", "InCorner"]
        
        file_exists = os.path.isfile(self.path)
        with open(self.path, "a", newline="") as file:
            writer = csv.writer(file)
            if not file_exists:
                writer.writerow(self.headers)

    def log_step(self, data):
        with open(self.path, "a", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(data)
