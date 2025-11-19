# ===== CONFIG =====
PORT                = "COM8"
STARTING_BAUD       = 9600
TX_NEWLINE          = "\r"

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
    ('STBRT 15000', BASE_DELAY),
    ("STSBR 115200", 0),
    ("STI",        	BASE_DELAY),
    ("STRSTNVM",    BASE_DELAY),
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

def send_and_log(ser: Serial, cmd: str, delay: float, log, num: int):
    """Send one command, wait, read response, and log everything."""
    visible = make_visible(bytes(cmd, 'utf-8'))
    write_log(log, f"\n--- [{num}] {visible} ---")
    print(f"[{num}] {visible}")

    cmd += TX_NEWLINE
    cmd_b = cmd.encode("ascii", errors="ignore")
    
    # Flush any stale bytes before sending a command.
    sleep(0.05)
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
                            else:
                                baud = STARTING_BAUD
                                continue
                        
                        seq = SEQUENCE[num:]
                        for cmd, delay in seq:
                            num = send_and_log(port, cmd, delay, log, num)
                            if cmd.upper().__contains__('STBRT'):
                                TIMEOUT = int([x for x in cmd.split() if x.isdigit()][0])*1.2
                            elif cmd.upper().__contains__('STSBR '):
                                STARTING_BAUD = baud
                                baud = int([x for x in cmd.split() if x.isdigit()][0])
                                break
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
