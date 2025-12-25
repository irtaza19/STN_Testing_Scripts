import os, time, serial
from datetime import datetime

# ===== CONFIG =====
PORT = "COM8"
BAUD = 9600
TX_NEWLINE = b"\r"

OVERALL_TIMEOUT_SEC = 15.0
READ_SLICE_SLEEP = 0.005

PAT_OK = b"OK\r"
PAT_BANNER = b"\r\rELM327 v1.4b\r\r>"

# ===== Helpers =====
def now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def visible_bytes(b: bytes) -> str:
    out = []
    for x in b:
        if x == 0x20: out.append("·")
        elif x == 0x0D: out.append("<CR>")
        elif x == 0x0A: out.append("<LF>\n")
        elif 0x09 <= x <= 0x0D: out.append(f"<0x{x:02X}>")
        elif 0x21 <= x <= 0x7E: out.append(chr(x))
        else: out.append(f"\\x{x:02X}")
    return "".join(out)

def hex_bytes(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)

def open_port(port, baud):
    return serial.Serial(port, baudrate=baud, timeout=0)

def drain(ser: serial.Serial):
    time.sleep(0.02)
    while ser.in_waiting:
        ser.read(ser.in_waiting)
        time.sleep(0.01)

def write_log(f, text: str):
    f.write(text + ("\n" if not text.endswith("\n") else ""))

# ===== LOG FILE =====
LOG_FILE = "STRSTNVM_T1.txt"

# ===== MAIN =====
def main():
    print(f"Opening {PORT} @ {BAUD}")
    ser = open_port(PORT, BAUD)

    with open(LOG_FILE, "w", encoding="utf-8") as log:
        write_log(log, "=== STRSTNVM T1 TIMING TEST ===")
        write_log(log, f"Started: {now_str()}")
        write_log(log, f"PORT = {PORT} @ Baud = {BAUD}\n")

        drain(ser)

        # Send command
        cmd = b"STRSTNVM" + TX_NEWLINE
        write_log(log, "TX: STRSTNVM<CR>")
        ser.write(cmd)

        rx_bytes = bytearray()
        rx_times = []

        t_deadline = time.time() + OVERALL_TIMEOUT_SEC
        ok_end_idx = None
        banner_start_idx = None
        t1 = None

        while time.time() < t_deadline:
            n = ser.in_waiting
            if n:
                chunk = ser.read(n)
                t_now = time.time()
                for b in chunk:
                    rx_bytes.append(b)
                    rx_times.append(t_now)

                if ok_end_idx is None:
                    pos = rx_bytes.find(PAT_OK)
                    if pos != -1:
                        ok_end_idx = pos + len(PAT_OK) - 1

                if ok_end_idx is not None and banner_start_idx is None:
                    pos = rx_bytes.find(PAT_BANNER, ok_end_idx + 1)
                    if pos != -1:
                        banner_start_idx = pos
                        t1 = rx_times[banner_start_idx] - rx_times[ok_end_idx]
                        break
            else:
                time.sleep(READ_SLICE_SLEEP)

        # ===== LOG OUTPUT =====
        write_log(log, f"\nRX len = {len(rx_bytes)}")
        write_log(log, visible_bytes(rx_bytes))
        write_log(log, "\nHEX:")
        write_log(log, hex_bytes(rx_bytes))

        if t1 is not None:
            write_log(log, f"\nT1 RESULT:")
            write_log(log, f"OK\\r ends at byte index: {ok_end_idx}")
            write_log(log, f"Banner starts at byte index: {banner_start_idx}")
            write_log(log, f"T1 = {t1:.6f} seconds")
            print(f"T1 = {t1:.6f} seconds")
        else:
            write_log(log, "\n❌ T1 NOT FOUND (pattern missing or timeout)")
            print("❌ T1 not found")

    ser.close()
    print(f"\n✅ Done. Log saved to: {os.path.abspath(LOG_FILE)}")

if __name__ == "__main__":
    main()
