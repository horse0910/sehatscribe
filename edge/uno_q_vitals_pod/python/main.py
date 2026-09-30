"""SehatScribe Vitals Pod — Linux side (Qualcomm Dragonwing QRB2210 on Arduino UNO Q).

Polls the MCU for a reading every few seconds, applies a simple plausibility
filter (edge anomaly check) and POSTs the result to the SehatScribe app on the
doctor's PC.

Configure with environment variables (or edit the defaults below):
  SEHAT_PC_URL        e.g. http://192.168.1.20:8000
  SEHAT_DEVICE_TOKEN  must match the token set on the PC
"""

import json
import os
import time
import urllib.request

from arduino.app_utils import App, Bridge

PC_URL = os.environ.get("SEHAT_PC_URL", "http://192.168.1.20:8000")
TOKEN = os.environ.get("SEHAT_DEVICE_TOKEN", "change-me")
POLL_S = 5

RANGES = {"temperature_f": (93.0, 108.0), "spo2": (70, 100), "pulse": (30, 200)}


def plausible(reading: dict) -> bool:
    return all(lo <= reading[k] <= hi for k, (lo, hi) in RANGES.items() if reading.get(k) is not None)


def send(reading: dict) -> None:
    req = urllib.request.Request(
        f"{PC_URL}/api/devices/vitals",
        data=json.dumps({"device_id": "uno-q-pod", **reading}).encode(),
        headers={"Content-Type": "application/json", "X-Device-Token": TOKEN},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=3) as resp:
        resp.read()


def loop():
    raw = Bridge.call("get_vitals")
    temp, spo2, pulse = str(raw).split(",")
    reading = {"temperature_f": float(temp), "spo2": int(spo2), "pulse": int(pulse)}
    if plausible(reading):
        try:
            send(reading)
            print("sent", reading)
        except OSError as exc:
            print("PC not reachable:", exc)
    else:
        print("discarded implausible reading", reading)
    time.sleep(POLL_S)


App.run(user_loop=loop)
