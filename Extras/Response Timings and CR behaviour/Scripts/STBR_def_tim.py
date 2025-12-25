# ===== CONFIG =====
PORT                = "COM8"
STARTING_BAUD       = 9600
TX_NEWLINE          = "\r"

IDLE_GAP_SEC        = 0.30   # stop reading after this much quiet time
READ_SLICE_SLEEP    = 0.004  # faster polling to catch immediate banner

BASE_DELAY          = 1
STRSTNVM_DELAY      = 3

# Default waits for fast events
OK_WAIT_SEC         = 0.20   # wait for OK\r after STBR at old baud
BANNER_WAIT_SEC     = 0.30   # wait for banner right after switching to new baud
PROMPT_WAIT_SEC     = 2.00   # wait for OK\r\r> after switching back to old baud

# Patterns
OK_CR               = b"OK\r"
BANNER              = b"STN2120 v5.6.5\r"
PROMPT              = b"OK\r\r>"

# ===== SEQUENCE (NO STBRT) =====
SEQUENCE = [
    ("STRSTNVM",    STRSTNVM_DELAY),
    ("STBR 115200", 0),
    ("STI",         BASE_DELAY),
    ("STRSTNVM",    BASE_DELAY),
    ("STI",         BASE_DELAY),
]

from serial     import Serial
from time       import sleep, time, monotonic
from datetime   import datetime
from os.path    import abspath, basename, splitext

# ===== HELPERS =====
def write_log(f, text: str):
    f.write(text + ("\n" if not text.endswith("\n") else ""))

def make_visible(data: bytes):
    chars = []
    for x in data:
        if not x:
            break
        if   x == 0x20:         chars.append("·")
        elif x == 0x0D:         chars.append("<CR>")
        elif x == 0x0A:         chars.append("<LF>\n")
        elif x == 0x09:         chars.append("<TAB>")
        elif 0x21 <= x <= 0x7E: chars.append(chr(x))
        else:                   chars.append(f"\\x{x:02X}")
    return "".join(chars)

def read_until(ser: Serial, delay: float = IDLE_GAP_SEC, command: bytes | None = None):
    """
    Read until the device is quiet for `delay` seconds OR until `command` is detected.
    Returns: (log_data, visible_bytes, hex_bytes, t_first, t_last, t_found)
    """
    buf = bytearray()
    last_rx_wall = time()

    t_first = None
    t_last  = None
    t_found = None

    while True:
        n = ser.in_waiting
        if n:
            chunk = ser.read(n)
            now = monotonic()
            if t_first is None:
                t_first = now
            t_last = now

            buf += chunk
            last_rx_wall = time()

            if command and (t_found is None) and (command in buf):
                t_found = now
                break

            sleep(READ_SLICE_SLEEP)
        elif (time() - last_rx_wall) >= delay:
            break
        else:
            sleep(READ_SLICE_SLEEP)

    log_data = bytes(buf)
    hex_bytes = " ".join(f"{x:02X}" if x else "\\0" for x in log_data)
    visible_bytes = make_visible(log_data)
    return log_data, visible_bytes, hex_bytes, t_first, t_last, t_found

def write_log_section(log, log_data, visible_bytes, hex_bytes):
    write_log(log, f"len={len(log_data)}\n{visible_bytes}\nHEX: {hex_bytes}")

def send_and_log_simple(ser: Serial, cmd: str, delay: float, log, num: int):
    """Generic command sender (used for non-STBR commands)."""
    visible = make_visible(cmd.encode("utf-8", errors="ignore"))
    write_log(log, f"\n--- [{num}] {visible} ---")
    print(f"[{num}] {visible}")

    if not cmd.endswith(TX_NEWLINE):
        cmd += TX_NEWLINE
    cmd_b = cmd.encode("ascii", errors="ignore")

    sleep(0.02)
    ser.reset_input_buffer()
    ser.write(cmd_b)

    if delay:
        sleep(delay)

    log_data, visible_bytes, hex_bytes, *_ = read_until(ser)
    if not visible_bytes:
        print("Warning: No visible bytes received")
    write_log_section(log, log_data, visible_bytes, hex_bytes)
    return num + 1

def stbr_fast_switch(ser: Serial, new_baud: int, log, num: int, old_baud: int):
    """
    Send STBR at OLD baud, read until OK\r, IMMEDIATELY switch baudrate in-place to NEW baud,
    then read banner at NEW baud, then switch back to OLD baud and read OK\r\r> there.

    Measures:
      T1 = time(old OK) -> time(banner)
      T2 = time(banner) -> time(prompt OK\r\r>) on OLD baud
    """
    cmd = f"STBR {new_baud}"
    visible = make_visible(cmd.encode("utf-8", errors="ignore"))
    write_log(log, f"\n--- [{num}] {visible} ---")
    print(f"[{num}] {visible}")

    ser.reset_input_buffer()
    ser.write((cmd + TX_NEWLINE).encode("ascii", errors="ignore"))

    # 1) Read ONLY until OK\r at OLD baud
    log_data_ok, vis_ok, hex_ok, tf, tl, t_ok = read_until(ser, delay=OK_WAIT_SEC, command=OK_CR)
    write_log_section(log, log_data_ok, vis_ok, hex_ok)

    t_ok_time = t_ok if t_ok is not None else tl

    # 2) Switch to NEW baud IN-PLACE immediately (no close/reopen)
    ser.baudrate = new_baud
    ser.reset_input_buffer()

    # 3) Read banner at NEW baud
    log_data_bn, vis_bn, hex_bn, tfb, tlb, t_bn = read_until(ser, delay=BANNER_WAIT_SEC, command=BANNER)
    write_log(log, "\n--- [BANNER @ NEW BAUD] ---")
    write_log_section(log, log_data_bn, vis_bn, hex_bn)

    t_banner_time = t_bn if t_bn is not None else tlb

    # 4) Do NOT send ACK. Switch back to OLD baud quickly, wait for OK\r\r> on OLD baud.
    ser.baudrate = old_baud
    ser.reset_input_buffer()

    log_data_pr, vis_pr, hex_pr, tfp, tlp, t_pr = read_until(ser, delay=PROMPT_WAIT_SEC, command=PROMPT)
    write_log(log, "\n--- [PROMPT @ OLD BAUD] ---")
    write_log_section(log, log_data_pr, vis_pr, hex_pr)

    t_prompt_time = t_pr if t_pr is not None else tlp

    # Compute times
    if (t_ok_time is not None) and (t_banner_time is not None):
        T1_ms = (t_banner_time - t_ok_time) * 1000.0
        print(f"T1 (old OK -> banner) = {T1_ms:.3f} ms")
        write_log(log, f"\nT1 (old OK -> banner) = {T1_ms:.3f} ms")

    if (t_banner_time is not None) and (t_prompt_time is not None):
        T2_ms = (t_prompt_time - t_banner_time) * 1000.0
        print(f"T2 (banner -> OK\\r\\r>) = {T2_ms:.3f} ms")
        write_log(log, f"T2 (banner -> OK\\r\\r>) = {T2_ms:.3f} ms")

    return num + 1

# ===== MAIN =====
def main():
    baud = STARTING_BAUD
    LOG_FILE = f"{splitext(basename(__file__))[0]}.txt"

    try:
        with open(LOG_FILE, "w", encoding="utf-8") as log:
            write_log(log, f"=== SEQUENCE TEST (FAST BAUD SWITCH, NO STBRT, NO ACK) ===\nStarted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Log file: {abspath(LOG_FILE)}")

            num = 0
            with Serial(PORT, baudrate=baud, timeout=0) as port:
                print(f"\nOpening PORT = {PORT} @ Baud = {baud} …")
                write_log(log, f"\nStarted: Baud = {baud}")

                for cmd, delay in SEQUENCE:
                    if cmd.upper().startswith("STBR "):
                        new_baud = int([x for x in cmd.split() if x.isdigit()][0])
                        num = stbr_fast_switch(port, new_baud=new_baud, log=log, num=num, old_baud=baud)

                        # After the handshake we stay at OLD baud (per your requirement)
                        port.baudrate = baud
                    else:
                        num = send_and_log_simple(port, cmd, delay, log, num)

    except Exception as e:
        print(f"❌ Error: {e}")
        return

    print(f"\n✅ Done. Log saved to: {abspath(LOG_FILE)}")

if __name__ == "__main__":
    main()
