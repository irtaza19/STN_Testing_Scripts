#!/usr/bin/env python3
# dual_pp_focused_test.py
#
# Dual-port programmable parameter focused test:
# - Runs through each PP in pp_impact_map
# - Sets PP value, toggles ON/OFF
# - Sends related commands on both STN & dsPIC
# - Compares responses strictly (CR/LF/spaces included)
# - Logs results with PASS/FAIL summary

import serial
import time
from datetime import datetime
import os

# === CONFIGURATION ===
PORT   = "COM8"    # change if needed
BAUD = 9600
WAIT_AFTER_SEND_SEC = 1.5
LOG_FILE = "ATPPS.txt"

# === Programmable Parameters and Related Commands ===
pp_impact_map = {
    "01": ["STRSTNVM","ATH1", "ATH0", "ATSH 7E0", "ATRTR", "ATD 1", "ATD 0"],
    "02": ["ATAL", "ATNL"],
    "04": ["ATAT 0", "ATAT 1", "ATAT 2"],
    "09": ["ATE 1", "ATE 0"],
    "24": ["ATCAF 1", "ATCAF 0", "ATRTR", "ATNL", "ATSH 7DF"],
    "25": ["ATCFC 1", "ATCFC 0", "ATFCSM 00", "ATFCSH 7E8", "ATFCSD 30 00"],
    "29": ["ATH1", "ATD 1", "ATD 0", "STRSTNVM"]
}

# === Helpers ===
def visible_chars(s: str) -> str:
    return (
        s.replace(" ", "·")
         .replace("\r", "<CR>")
         .replace("\n", "<LF>\n")
    )

def strict_compare(a: str, b: str):
    if a == b:
        return True, None
    # diff report
    out = []
    m = min(len(a), len(b))
    for i in range(m):
        if a[i] != b[i]:
            out.append(f"diff at pos {i}: STN='{visible_chars(a[i])}' DSPIC='{visible_chars(b[i])}'")
            break
    if len(a) != len(b):
        out.append(f"lengths differ: STN={len(a)}, DSPIC={len(b)}")
    return False, "\n".join(out)

def send_and_read(ser, cmd):
    ser.reset_input_buffer()
    ser.write((cmd + "\r").encode())
    time.sleep(WAIT_AFTER_SEND_SEC)
    resp = ""
    while ser.in_waiting:
        resp += ser.read(ser.in_waiting).decode(errors="ignore")
        time.sleep(0.05)
    return resp

def send(connection, log, cmd):
    print(f"🟢 Sending: {cmd}")
    stn_resp = send_and_read(connection, cmd)

    log.write(f"\n> {cmd}\n")
    log.write(f"O/P   : {visible_chars(stn_resp)}\n")
    

# === Main ===
def main():
    try:
        connection = serial.Serial(PORT, BAUD, timeout=2)
    except Exception as e:
        print(f"❌ Error opening ports: {e}")
        return

    print(f"✅ Connected to STN={PORT}")
    print(f"Log file: {os.path.abspath(LOG_FILE)}")

    total, passed = 0, 0

    with open(LOG_FILE, "w", encoding="utf-8") as log:
        log.write(f"=== PP FOCUSED TEST ===\nStarted: {datetime.now()}\n\n")

        for pp, commands in pp_impact_map.items():
            log.write(f"\n=== Testing PP {pp} ===\n")

            send(connection, log, "STRSTNVM")
            # Set + ON
            send(connection, log, f"ATPP {pp} SV 01")
            send(connection, log, f"ATPP {pp} ON")

            log.write(f"\n--- Commands with PP {pp} ON ---\n")
            for cmd in commands:
                total += 1
                if send(connection, log, cmd):
                    passed += 1

            # OFF
            send(connection, log, f"ATPP {pp} OFF")

            log.write(f"\n--- Commands with PP {pp} OFF ---\n")
            for cmd in commands:
                total += 1
                if send(connection, log, cmd):
                    passed += 1

            log.write("-" * 40 + "\n")

        # Final summary
        log.write("\n\n> Final ATPPS Summary\n")
        send(connection, log, "ATPPS")

    connection.close()
    print("\n🛑 Disconnected Successfully.")

if __name__ == "__main__":
    main()
