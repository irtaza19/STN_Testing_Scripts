# ===== CONFIG =====
PORT                = "COM8"
STARTING_BAUD       = 9600
TX_NEWLINE          = "\r"

IDLE_GAP_SEC        = 0.3                       # stop reading after this much quiet time (non-STSBR)
READ_SLICE_SLEEP    = 0.02                      # poll interval
BASE_DELAY          = 1
STRSTNVM_DELAY      = 3
ATZ_DELAY           = 2

# STSBR-specific: wait up to this long for the '>' prompt after OK
STSBR_PROMPT_TIMEOUT_SEC = 6.0

TIMEOUT             = 1
COMMAND_TO_RECEIVE  = b">"
COMMAND_TO_SEND     = "\r"

# ===== SEQUENCE =====
SEQUENCE = [
    ("STRSTNVM",    STRSTNVM_DELAY),
    ("STBRT 5000",    BASE_DELAY),
    ("STSBR 9600",  0),
    ("STRSTNVM",    BASE_DELAY),
    ("STI",         BASE_DELAY),
]

from serial     import Serial
from time       import sleep, time
from datetime   import datetime
from os.path    import abspath, basename, splitext

# ===== HELPERS =====
def write_log(f, text: str):
    f.write(text + ("\n" if not text.endswith("\n") else ""))

def make_visible(b: bytes) -> str:
    chars = []
    for x in b:
        if not x:
            break
        if x == 0x20:
            chars.append("·")
        elif x == 0x0D:
            chars.append("<CR>")
        elif x == 0x0A:
            chars.append("<LF>\n")
        elif x == 0x09:
            chars.append("<TAB>")
        elif 0x21 <= x <= 0x7E:
            chars.append(chr(x))
        else:
            chars.append(f"\\x{x:02X}")
    return "".join(chars)

def read_until(ser: Serial, idle_gap: float = IDLE_GAP_SEC, command: bytes | None = None):
    """
    Read until the device is quiet for `idle_gap`, or until `command` appears.
    """
    buf = bytearray()
    last_rx = time()

    while True:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
            last_rx = time()
        else:
            if command is not None and command in buf:
                break
            if (time() - last_rx) >= idle_gap:
                break
            sleep(READ_SLICE_SLEEP)

    log_data = bytes(buf)
    hex_bytes = " ".join(f"{x:02X}" if x else "\\0" for x in log_data)
    visible_bytes = make_visible(log_data)
    return log_data, visible_bytes, hex_bytes

def write_log_section(log, log_data: bytes, visible_bytes: str, hex_bytes: str):
    write_log(log, f"len={len(log_data)}\n{visible_bytes}\nHEX: {hex_bytes}")

def read_stsbr_t1_t2(ser: Serial, t_tx: float, prompt_timeout_sec: float = STSBR_PROMPT_TIMEOUT_SEC):
    """
    For STSBR:
      - T1: TX -> first 'OK'
      - T2: OK -> first '>' after that OK
    Important:
      - Ignore any '\\r' (or any bytes) between OK and '>' (we just search for '>' after OK).
      - Wait up to `prompt_timeout_sec` seconds total from TX for the '>' prompt.
    Returns: (data_bytes, ok_time, prompt_time)
    """
    buf = bytearray()
    ok_time = None
    prompt_time = None
    ok_search_from = 0
    prompt_search_from = 0

    deadline = t_tx + float(prompt_timeout_sec)

    while True:
        now = time()
        if now >= deadline:
            break

        n = ser.in_waiting
        if n:
            chunk = ser.read(n)
            buf += chunk

            # Find OK once
            if ok_time is None:
                p_ok = buf.find(b"OK", ok_search_from)
                if p_ok != -1:
                    ok_time = time()
                    prompt_search_from = p_ok + 2  # start searching AFTER 'OK'

            # Find '>' only after OK
            if ok_time is not None and prompt_time is None:
                p_gt = buf.find(b">", prompt_search_from)
                if p_gt != -1:
                    prompt_time = time()
                    break  # Stop as soon as prompt arrives

        else:
            # Keep waiting until timeout (requirement: wait until '>' or 6s max)
            sleep(READ_SLICE_SLEEP)

    return bytes(buf), ok_time, prompt_time

def send_and_log(ser: Serial, cmd: str, delay: float, log, num: int):
    visible_cmd = make_visible(cmd.encode("utf-8", errors="ignore"))
    write_log(log, f"\n--- [{num}] {visible_cmd} ---")
    print(f"[{num}] {visible_cmd}")

    cmd_to_send = (cmd + TX_NEWLINE).encode("ascii", errors="ignore")

    sleep(0.05)
    ser.reset_input_buffer()

    # TX timestamp
    t_tx = time()
    ser.write(cmd_to_send)

    # SPECIAL: STSBR timing (T1 + T2)
    if "STSBR" in cmd.upper():
        data, ok_t, prompt_t = read_stsbr_t1_t2(
            ser,
            t_tx=t_tx,
            prompt_timeout_sec=STSBR_PROMPT_TIMEOUT_SEC
        )

        write_log(log, f"TX time: {t_tx:.6f}")

        if ok_t is not None:
            t1_ms = (ok_t - t_tx) * 1000.0
            write_log(log, f"T1 (TX -> OK): {t1_ms:.3f} ms")
        else:
            write_log(log, "OK not received (cannot compute T1/T2)")

        if ok_t is not None and prompt_t is not None:
            t2_ms = (prompt_t - ok_t) * 1000.0
            write_log(log, f"T2 (OK -> '>'): {t2_ms:.3f} ms")
        elif ok_t is not None and prompt_t is None:
            write_log(log, f"Prompt ('>') not received within {STSBR_PROMPT_TIMEOUT_SEC:.1f} s (cannot compute T2)")

        visible_bytes = make_visible(data)
        hex_bytes = " ".join(f"{x:02X}" for x in data)
        write_log_section(log, data, visible_bytes, hex_bytes)

        # If '>' not received within timeout, move on.
        return num + 1

    # NORMAL PATH
    sleep(delay)
    log_data, visible_bytes, hex_bytes = read_until(ser, idle_gap=IDLE_GAP_SEC)

    if not visible_bytes:
        print("Warning: No visible bytes received")

    write_log_section(log, log_data, visible_bytes, hex_bytes)
    return num + 1

# ===== MAIN =====
def main():
    for file in range(1):
        LOG_FILE = f"{splitext(basename(__file__))[0]}{file if file else ''}.txt"
        baud = STARTING_BAUD

        try:
            with open(LOG_FILE, "w", encoding="utf-8") as log:
                write_log(log, "=== SEQUENCE TEST ===")
                write_log(log, f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"Log file: {abspath(LOG_FILE)}")

                num = 0
                while num < len(SEQUENCE):
                    print(f"\nOpening PORT = {PORT} @ Baud = {baud} …")
                    write_log(log, f"\nStarted: Baud = {baud}")

                    with Serial(PORT, baudrate=baud, timeout=0) as port:
                        seq = SEQUENCE[num:]
                        for cmd, delay in seq:
                            num = send_and_log(port, cmd, delay, log, num)

        except Exception as e:
            print(f"❌ Error: {e}")
            return

        print(f"\n✅ Done. Log saved to: {abspath(LOG_FILE)}")

# ===== ENTRYPOINT =====
if __name__ == "__main__":
    main()