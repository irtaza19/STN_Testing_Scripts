import os, time, serial
from datetime import datetime

# ===== CONFIG =====
PORT = "COM8"
BAUD = 9600
TX_NEWLINE = b"\r"

OVERALL_TIMEOUT_SEC = 10.0
READ_SLICE_SLEEP = 0.005

# Response: OK\r\r>
PAT_PROMPT = b">"  # we measure time to this byte

# ===== Helpers =====
def now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def visible_bytes(b: bytes) -> str:
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
    time.sleep(0.02)
    while ser.in_waiting:
        ser.read(ser.in_waiting)
        time.sleep(0.01)

# ===== LOG FILE =====
LOG_FILE = "ATD_T1.txt"

# ===== MAIN =====
def main():
    print(f"Opening {PORT} @ {BAUD} …")
    try:
        ser = open_port(PORT, BAUD)
    except Exception as e:
        print(f"❌ Error opening port: {e}")
        return

    print(f"Log file: {os.path.abspath(LOG_FILE)}")

    with open(LOG_FILE, "w", encoding="utf-8") as log:
        write_log(log, "=== ATD T1 TIMING TEST ===")
        write_log(log, f"Started: {now_str()}")
        write_log(log, f"PORT = {PORT} @ Baud = {BAUD}\n")
        write_log(log, 'Expected RX (example): OK<CR><CR>>')

        drain(ser)

        # Send ATD
        cmd = b"ATD" + TX_NEWLINE
        write_log(log, "\nTX: ATD<CR>")

        t_tx = time.time()
        ser.write(cmd)

        # Capture with timestamps
        rx_bytes = bytearray()
        rx_times = []  # timestamp per byte (chunk timestamp applied per byte)

        t_deadline = t_tx + OVERALL_TIMEOUT_SEC
        prompt_idx = None
        t1 = None

        while time.time() < t_deadline:
            n = ser.in_waiting
            if n:
                chunk = ser.read(n)
                t_now = time.time()
                for b in chunk:
                    rx_bytes.append(b)
                    rx_times.append(t_now)

                # Find first '>' in the received stream
                pos = rx_bytes.find(PAT_PROMPT)
                if pos != -1:
                    prompt_idx = pos
                    t_prompt = rx_times[prompt_idx]
                    t1 = t_prompt - t_tx
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
            write_log(log, f"ATD TX time (epoch): {t_tx:.6f}")
            write_log(log, f"Prompt '>' at byte index: {prompt_idx}")
            write_log(log, f"T1 (TX->'>') = {t1:.6f} seconds")
            print(f"T1 (TX->'>') = {t1:.6f} seconds")
        else:
            write_log(log, "\n❌ T1 NOT FOUND (no '>' prompt or timeout)")
            print("❌ T1 not found (no '>' prompt or timeout)")

    try:
        ser.close()
    except:
        pass

    print(f"\n✅ Done. Log saved to: {os.path.abspath(LOG_FILE)}")

if __name__ == "__main__":
    main()
