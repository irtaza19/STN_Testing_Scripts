import os, time, serial
from datetime import datetime

# ===== CONFIG =====
PORT        = "COM8"
BAUD        = 9600
TX_NEWLINE  = b"\r"

IDLE_GAP_SEC        = 0.30     # stop reading after this much quiet time
READ_SLICE_SLEEP    = 0.04
BASE_WAIT_SEC       = 2.0
WAIT_AFTER_STRSTNVM = 3.0

# ===== SEQUENCE (exactly as requested; note spaces vs no spaces) =====
SEQUENCE = [
    ("STRSTNVM", WAIT_AFTER_STRSTNVM),
    ("0902", 7),
    ("STPX H:7E8, D:0902", BASE_WAIT_SEC),
    ("STPX H:7E8, L:2", BASE_WAIT_SEC),
    ("0902", BASE_WAIT_SEC),
    ("STPX D:0902", BASE_WAIT_SEC),
    ("STPX H:777, D:0902", BASE_WAIT_SEC),
    ("STPX", BASE_WAIT_SEC),
    ("STPX 0, L:2", BASE_WAIT_SEC),
    ("STPX H:777, L:2", BASE_WAIT_SEC),
    ("0902", BASE_WAIT_SEC),
    ("STPX H:, L:2", BASE_WAIT_SEC),
    ("STPX ::, L:2", BASE_WAIT_SEC),
]

# ===== Helpers =====
def now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def visible_bytes(b: bytes) -> str:
    """Render spaces/CR/LF clearly for strict auditing."""
    out = []
    for x in b:
        if x == 0x20: out.append("·")
        elif x == 0x0D: out.append("<CR>")
        elif x == 0x0A: out.append("<LF>\n")
        elif x == 0x09: out.append("<TAB>")
        elif 0x21 <= x <= 0x7E: out.append(chr(x))
        else: out.append(f"\\x{x:02X}")
    return "".join(out)

def hex_bytes(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)

def write_log(f, text: str):
    f.write(text + ("\n" if not text.endswith("\n") else ""))

def open_port(port, baud):
    return serial.Serial(port, baudrate=baud, timeout=0)

def drain(ser: serial.Serial):
    """Clear any pending bytes so reads are for current command only."""
    time.sleep(0.02)
    while ser.in_waiting:
        ser.read(ser.in_waiting)
        time.sleep(0.01)

def read_until_quiet(ser: serial.Serial) -> bytes:
    buf = bytearray()
    last_rx = time.time()
    while True:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
            last_rx = time.time()
            time.sleep(READ_SLICE_SLEEP)
        else:
            if (time.time() - last_rx) >= IDLE_GAP_SEC:
                break
            time.sleep(READ_SLICE_SLEEP)
    return bytes(buf)

# ===== LOG FILE =====

LOG_FILE = f"{os.path.splitext(os.path.basename(__file__))[0]}.txt"

# ===== MAIN =====

def main():
    print(f"Opening PORT = {PORT} @ Baud = {BAUD} …")
    try:
        port = open_port(PORT, BAUD)
    except Exception as e:
        print(f"❌ Error opening ports: {e}")
        return

    print(f"Log file: {os.path.abspath(LOG_FILE)}")

    with open(LOG_FILE, "w", encoding="utf-8") as log:
        write_log(log, "=== SEQUENCE TEST ===")
        write_log(log, f"Started: {now_str()}")
        write_log(log, f"PORT = {PORT} @ Baud = {BAUD}\n")

        for idx, (cmd, delay) in enumerate(SEQUENCE):
            write_log(log, f"\n--- [{idx}] {cmd} ---")
            print(f"[{idx}] {cmd}")

            cmd_b = cmd.encode("ascii", errors="ignore")
            drain(port)

            # send, wait, then read full response
            port.write(cmd_b + TX_NEWLINE)
            time.sleep(delay)

            log_data = read_until_quiet(port)

            # log raw
            write_log(log, f"len={len(log_data)}")
            write_log(log, visible_bytes(log_data))
            write_log(log, "HEX: " + hex_bytes(log_data))

    try:
        port.close()
    except: pass

    print(f"\n✅ Done. Log saved to: {LOG_FILE}")

if __name__ == "__main__":
    main()
