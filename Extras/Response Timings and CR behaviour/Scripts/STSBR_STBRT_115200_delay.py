# ===== CONFIG =====
PORT                = "COM8"
STARTING_BAUD       = 9600
TX_NEWLINE          = "\r"

IDLE_GAP_SEC        = 0.3                       # stop reading after this much quiet time (non-STSBR)
READ_SLICE_SLEEP    = 0.02                      # poll interval
BASE_DELAY          = 1
STRSTNVM_DELAY      = 3
ATZ_DELAY           = 2

# STSBR-specific: wait up to this long (from TX) for the '>' prompt
STSBR_PROMPT_TIMEOUT_SEC = 6.0

# ===== SEQUENCE =====
SEQUENCE = [
    ("STRSTNVM",     STRSTNVM_DELAY),
    ("STBRT 5000",     BASE_DELAY),
    ("STSBR 115200", 0),            # <- change baud to 115200 on the device
    ("STRSTNVM",     STRSTNVM_DELAY),
    ("STI",          BASE_DELAY),
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

def read_until_idle(ser: Serial, idle_gap: float = IDLE_GAP_SEC) -> bytes:
    """
    Read until the device is quiet for `idle_gap`.
    """
    buf = bytearray()
    last_rx = time()
    while True:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
            last_rx = time()
        else:
            if (time() - last_rx) >= idle_gap:
                break
            sleep(READ_SLICE_SLEEP)
    return bytes(buf)

def write_log_section(log, log_data: bytes):
    visible_bytes = make_visible(log_data)
    hex_bytes = " ".join(f"{x:02X}" for x in log_data)
    write_log(log, f"len={len(log_data)}\n{visible_bytes}\nHEX: {hex_bytes}")

def parse_stsbr_baud(cmd: str) -> int | None:
    """
    Extract baud from 'STSBR <baud>' command.
    Returns None if not parseable.
    """
    parts = cmd.strip().split()
    if len(parts) >= 2 and parts[0].upper() == "STSBR":
        try:
            return int(parts[1])
        except ValueError:
            return None
    return None

def read_stsbr_with_baud_switch(ser: Serial, t_tx: float, new_baud: int, timeout_sec: float = STSBR_PROMPT_TIMEOUT_SEC):
    """
    STSBR behavior (as you described):
      - At current baud, device replies: ... 'OK' then first '\\r'
      - After first '\\r', device switches its UART baud to `new_baud`
      - Then it outputs: second '\\r' and '>' at the new baud

    Measurements:
      T1 = TX -> 'OK'
      T2 = 'OK' -> '>'  (same definition, even though baud changes in between)

    Implementation:
      1) Read at OLD baud until we see 'OK' and the first CR after OK.
      2) Switch host/terminal baud (ser.baudrate = new_baud).
      3) Continue reading until we see '>' (after OK), or timeout.
         Any '\\r' bytes in-between are ignored naturally because we search for '>' after OK.

    Returns:
      data_all: bytes captured (old + new baud phases, concatenated)
      ok_time: timestamp when OK detected
      prompt_time: timestamp when '>' detected (may be None if timeout)
      cr1_time: timestamp when first CR after OK detected (may be None)
    """
    buf_old = bytearray()
    buf_new = bytearray()

    ok_time = None
    prompt_time = None
    cr1_time = None

    ok_pos_end = 0  # index after 'OK' in buf_old; used to search for CR after OK

    deadline = t_tx + float(timeout_sec)

    # ---- Phase 1: old baud, wait for OK and first CR after OK ----
    while True:
        now = time()
        if now >= deadline:
            break

        n = ser.in_waiting
        if n:
            chunk = ser.read(n)
            buf_old += chunk

            if ok_time is None:
                p_ok = buf_old.find(b"OK")
                if p_ok != -1:
                    ok_time = time()
                    ok_pos_end = p_ok + 2  # after OK

            if ok_time is not None and cr1_time is None:
                p_cr = buf_old.find(b"\r", ok_pos_end)
                if p_cr != -1:
                    cr1_time = time()
                    # As soon as we have the first CR after OK, switch baud.
                    break

        sleep(READ_SLICE_SLEEP)

    # Switch baud only if we reached CR1 (your requirement)
    if cr1_time is not None:
        try:
            ser.baudrate = new_baud
        except Exception:
            pass

        # Optional tiny pause to let host UART settle
        sleep(0.01)

        # Drop any bytes buffered at the old baud at the transition
        try:
            ser.reset_input_buffer()
        except Exception:
            pass

    # ---- Phase 2: new baud, wait for '>' ----
    while True:
        now = time()
        if now >= deadline:
            break

        n = ser.in_waiting
        if n:
            chunk = ser.read(n)
            buf_new += chunk

            if b">" in buf_new:
                prompt_time = time()
                break

        sleep(READ_SLICE_SLEEP)

    data_all = bytes(buf_old) + bytes(buf_new)
    return data_all, ok_time, prompt_time, cr1_time

# ===== CORE =====
def send_and_log(ser: Serial, cmd: str, delay: float, log, num: int):
    """
    Sends one command, logs response.
    Returns: (next_num, updated_baud_or_None)
    """
    visible_cmd = make_visible(cmd.encode("utf-8", errors="ignore"))
    write_log(log, f"\n--- [{num}] {visible_cmd} ---")
    print(f"[{num}] {visible_cmd}")

    cmd_to_send = (cmd + TX_NEWLINE).encode("ascii", errors="ignore")

    sleep(0.05)
    ser.reset_input_buffer()

    # TX timestamp
    t_tx = time()
    ser.write(cmd_to_send)

    # SPECIAL: STSBR with baud switch handling
    if cmd.strip().upper().startswith("STSBR"):
        new_baud = parse_stsbr_baud(cmd)
        if new_baud is None:
            write_log(log, "ERROR: Could not parse baud from STSBR command.")
            sleep(delay)
            data = read_until_idle(ser, idle_gap=IDLE_GAP_SEC)
            write_log_section(log, data)
            return num + 1, None

        data, ok_t, prompt_t, cr1_t = read_stsbr_with_baud_switch(
            ser,
            t_tx=t_tx,
            new_baud=new_baud,
            timeout_sec=STSBR_PROMPT_TIMEOUT_SEC
        )

        write_log(log, f"TX time: {t_tx:.6f}")

        if ok_t is not None:
            t1_ms = (ok_t - t_tx) * 1000.0
            write_log(log, f"T1 (TX -> OK): {t1_ms:.3f} ms")
        else:
            write_log(log, "OK not received (cannot compute T1/T2)")

        if cr1_t is not None:
            cr1_ms = (cr1_t - t_tx) * 1000.0
            write_log(log, f"CR1 after OK seen at: {cr1_ms:.3f} ms (then host baud -> {new_baud})")
        else:
            write_log(log, f"First CR after OK not seen before timeout; host baud not switched to {new_baud}")

        if ok_t is not None and prompt_t is not None:
            t2_ms = (prompt_t - ok_t) * 1000.0
            write_log(log, f"T2 (OK -> '>'): {t2_ms:.3f} ms")
        elif ok_t is not None and prompt_t is None:
            write_log(log, f"Prompt ('>') not received within {STSBR_PROMPT_TIMEOUT_SEC:.1f} s (cannot compute T2)")

        write_log_section(log, data)

        # Keep terminal baud at the new baud for subsequent commands
        return num + 1, new_baud

    # NORMAL PATH
    sleep(delay)
    data = read_until_idle(ser, idle_gap=IDLE_GAP_SEC)
    write_log_section(log, data)
    return num + 1, None

# ===== MAIN =====
def main():
    LOG_FILE = f"{splitext(basename(__file__))[0]}.txt"
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
                        num, maybe_new_baud = send_and_log(port, cmd, delay, log, num)
                        if maybe_new_baud is not None:
                            baud = maybe_new_baud  # keep for future opens as well

    except Exception as e:
        print(f"❌ Error: {e}")
        return

    print(f"\n✅ Done. Log saved to: {abspath(LOG_FILE)}")

# ===== ENTRYPOINT =====
if __name__ == "__main__":
    main()
