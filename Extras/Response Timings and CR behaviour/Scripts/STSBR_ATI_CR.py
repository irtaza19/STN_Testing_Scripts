# ===== CONFIG =====
PORT                = "COM8"
STARTING_BAUD       = 9600
TX_NEWLINE          = "\r"


# Fast baud-switch tuning (device switches within ~75ms)
STSBR_GUARD_SEC     = 0.005   # 10ms guard time before switching PC baud
STSBR_OLD_READ_SEC  = 0.020   # 20ms optional sniff at old baud (set 0 to disable)
IDLE_GAP_SEC        = 0.3                       # stop reading after this much quiet time
READ_SLICE_SLEEP    = 0.04                      # check serial port for new data after this much time
BASE_DELAY          = 1
STRSTNVM_DELAY      = 3
ATZ_DELAY           = 2

TIMEOUT             = 1
COMMAND_TO_RECEIVE  = b">"
COMMAND_TO_SEND     = '\r'

# ===== SEQUENCE =====
SEQUENCE = [
    ("STRSTNVM",    STRSTNVM_DELAY),
    ("STSBR 115200", 5),
    ("ATI",        	BASE_DELAY),
    ("\r",        	BASE_DELAY),
    ("STRSTNVM",    STRSTNVM_DELAY),
    ("STI",        	BASE_DELAY),
]

from serial     import Serial
from time       import sleep, time
from datetime   import datetime
from os.path    import abspath, basename, splitext

# ===== HELPERS =====
def write_log(f, text:str):
    f.write(text + ("\n" if not text.endswith("\n") else ""))
    
def read_until(ser:Serial, delay:float=IDLE_GAP_SEC, command=None):
    # Keep reading until the device is quiet for IDLE_GAP_SEC.
    buf = bytearray()
    last_rx = time()
    while True:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
            last_rx = time()
            sleep(READ_SLICE_SLEEP)
        elif (time() - last_rx) >= delay:
            break
        else:
            if command:
                if command in buf: break
            sleep(READ_SLICE_SLEEP)
    log_data = bytes(buf)
    
    hex_bytes = " ".join(f"{x:02X}" if x else '\0' for x in log_data)
    visible_bytes = make_visible(log_data)

    return log_data, visible_bytes, hex_bytes

def make_visible(bytes):
    chars = []
    for x in bytes:
        if not x: break
        if   x == 0x20:         chars.append("·")
        elif x == 0xd:          chars.append("<CR>")
        elif x == 0xa:          chars.append("<LF>\n")
        elif x == 0x9:          chars.append("<TAB>")
        elif 0x21 <= x <= 0x7E: chars.append(chr(x))
        else:                   chars.append(f"\\x{x:02X}")
    visible_bytes = "".join(chars)
    return visible_bytes

def write_log_section(log, log_data, visible_bytes, hex_bytes):
    write_log(log, f"len={len(log_data)}\n{visible_bytes}\nHEX: {hex_bytes}")


def send_stsbr_and_switch_baud(ser: Serial, cmd: str, log, num: int):
    """
    Send STSBR <baud>, then switch PC baud quickly (sub-75ms target),
    and read the response at the NEW baud.
    """
    visible = make_visible(bytes(cmd, 'utf-8'))
    write_log(log, f"\n--- [{num}] {visible} (FAST BAUD SWITCH) ---")
    print(f"[{num}] {visible} (FAST BAUD SWITCH)")

    # Parse target baud from e.g. "STSBR 115200"
    parts = cmd.split()
    new_baud = int([x for x in parts if x.isdigit()][0])

    full_cmd = (cmd + TX_NEWLINE).encode("ascii", errors="ignore")

    # Clear stale bytes, send at current baud
    ser.reset_input_buffer()
    ser.write(full_cmd)

    # Optional short read at old baud (often empty / garbage after device switches)
    if STSBR_OLD_READ_SEC and STSBR_OLD_READ_SEC > 0:
        old_data, old_vis, old_hex = read_until(ser, delay=STSBR_OLD_READ_SEC)
        if old_vis:
            write_log(log, f"\n[pre-switch @ old baud {ser.baudrate}]")
            write_log_section(log, old_data, old_vis, old_hex)

    # Small guard time then switch PC baud quickly
    sleep(STSBR_GUARD_SEC)
    ser.baudrate = new_baud

    # Drop any partial bytes caused by switching mid-stream
    ser.reset_input_buffer()

    # Read response at NEW baud (idle-gap based)
    log_data, visible_bytes, hex_bytes = read_until(ser, delay=IDLE_GAP_SEC)

    if not visible_bytes:
        print("Warning: No visible bytes received after baud switch")

    write_log(log, f"\n[post-switch @ new baud {new_baud}]")
    write_log_section(log, log_data, visible_bytes, hex_bytes)

    return num + 1, new_baud


def send_and_log(ser: Serial, cmd: str, delay: float, log, num: int):
    # FAST PATH: STSBR switches baud almost immediately on the device.
    if cmd.upper().startswith("STSBR "):
        num, _ = send_stsbr_and_switch_baud(ser, cmd, log, num)
        return num

    """Send one command, wait, read response, and log everything."""
    visible = make_visible(bytes(cmd, 'utf-8'))
    write_log(log, f"\n--- [{num}] {visible} ---")
    print(f"[{num}] {visible}")

    cmd += TX_NEWLINE
    cmd_b = cmd.encode("ascii", errors="ignore")

    # Flush any stale bytes before sending a command (keep this short for low latency).
    ser.reset_input_buffer()

    ser.write(cmd_b)
    sleep(delay)

    log_data, visible_bytes, hex_bytes = read_until(ser)

    if not visible_bytes:
        print('Warning: No visible bytes received')

    write_log_section(log, log_data, visible_bytes, hex_bytes)

    return num + 1

# ===== MAIN =====
def main():
    global STARTING_BAUD, TIMEOUT, SEQUENCE
    for file in range(1):
        LOG_FILE = f"{splitext(basename(__file__))[0]}{file if file else ''}.txt"
        baud = STARTING_BAUD
        try:
            with open(LOG_FILE, "w", encoding="utf-8") as log:
                write_log(log, f"=== SEQUENCE TEST ===\nStarted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"Log file: {abspath(LOG_FILE)}")
                
                num = 0            
                while num < len(SEQUENCE):
                    print(f"\nOpening PORT = {PORT} @ Baud = {baud} …")
                    write_log(log, f"\nStarted: Baud = {baud}")
                    
                    with Serial(PORT, baudrate=baud, timeout=0) as port:
                        if STARTING_BAUD != baud:
                            log_data, visible_bytes, hex_bytes = read_until(port, TIMEOUT, COMMAND_TO_RECEIVE)
                            print('Received: ', visible_bytes)
                            write_log_section(log, log_data, visible_bytes, hex_bytes)
                            if COMMAND_TO_RECEIVE in log_data:
                                print(f'"{COMMAND_TO_RECEIVE}" successfully received within {TIMEOUT} s.')
                            #else:
                                #baud = STARTING_BAUD
                                #continue
                        
                        seq = SEQUENCE[num:]
                        for cmd, delay in seq:
                            num = send_and_log(port, cmd, delay, log, num)
                            if cmd.upper().__contains__('STBRT'):
                                TIMEOUT = int([x for x in cmd.split() if x.isdigit()][0])*1.2
                            elif cmd.upper().__contains__('STSBR '):
                                STARTING_BAUD = baud
                                baud = int([x for x in cmd.split() if x.isdigit()][0])
                                # Port baud is switched live inside send_and_log(); keep going without reopen.
                                continue
                            elif cmd.upper().__contains__('STRSTNVM') and (baud != 9600):
                                STARTING_BAUD = baud = 9600
                                TIMEOUT = 1
                                break

        except Exception as e:
            print(f"❌ Error: {e}")
            return

        print(f"\n✅ Done. Log saved to: {abspath(LOG_FILE)}")

# ===== ENTRYPOINT =====
if __name__ == "__main__":
    main()
