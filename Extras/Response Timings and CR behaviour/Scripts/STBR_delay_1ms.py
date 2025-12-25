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
COMMAND_TO_RECEIVE  = b"STN2120 v5.6.5"
COMMAND_TO_SEND     = '\r'

# Handshake patterns at NEW baud
BANNER              = b"STN2120 v5.6.5\r"
PROMPT              = b"OK\r\r>"

# Timing globals (monotonic seconds)
t_ok_old = None   # timestamp when old-baud OK\r (after STBR) completed

# ===== SEQUENCE =====
SEQUENCE = [
    ("STRSTNVM",    STRSTNVM_DELAY),
    ('STBRT 1', BASE_DELAY),
    ("STBR 115200", 0),
    ("STI",        	BASE_DELAY),
    ("STRSTNVM",    BASE_DELAY),
    ("STI",        	BASE_DELAY),
]

from serial     import Serial
from time       import sleep, time, monotonic
from datetime   import datetime
from os.path    import abspath, basename, splitext

# ===== HELPERS =====
def write_log(f, text:str):
    f.write(text + ("\n" if not text.endswith("\n") else ""))
    
def read_until(ser:Serial, delay:float=IDLE_GAP_SEC, command=None):
    '''
    Keep reading until the device is quiet for `delay` seconds OR until `command` is detected.
    Returns: (log_data, visible_bytes, hex_bytes, t_first, t_last, t_found)
      - t_first: monotonic timestamp of first received byte (None if no data)
      - t_last : monotonic timestamp of last received byte (None if no data)
      - t_found: monotonic timestamp when `command` is first detected in the buffer (None if not used/not found)
    '''
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

            # Stop immediately if target pattern is detected
            if command and (t_found is None) and (command in buf):
                t_found = now
                break

            sleep(READ_SLICE_SLEEP)

        elif (time() - last_rx_wall) >= delay:
            break
        else:
            sleep(READ_SLICE_SLEEP)

    log_data = bytes(buf)

    hex_bytes = " ".join(f"{x:02X}" if x else '\0' for x in log_data)
    visible_bytes = make_visible(log_data)

    return log_data, visible_bytes, hex_bytes, t_first, t_last, t_found

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
    global t_ok_old
    """Send one command, wait, read response, and log everything."""
    visible = make_visible(bytes(cmd, 'utf-8'))
    write_log(log, f"\n--- [{num}] {visible} ---")
    print(f"[{num}] {visible}")

    if not cmd.endswith(TX_NEWLINE): cmd += TX_NEWLINE
    cmd_b = cmd.encode("ascii", errors="ignore")
    
    # Flush any stale bytes before sending a command.
    sleep(0.05)
    ser.reset_input_buffer()

    ser.write(cmd_b)
    sleep(delay)

    log_data, visible_bytes, hex_bytes, t_first, t_last, t_found = read_until(ser)
    
    if not visible_bytes:
        print('Warning: No visible bytes received')

    write_log_section(log, log_data, visible_bytes, hex_bytes)

    # Capture timestamp for the first OK at OLD baud (response to STBR ...)
    if cmd.upper().startswith('STBR ') and (b'OK\r' in log_data) and (t_last is not None):
        t_ok_old = t_last

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
                            # We are at NEW baud after STBR. Measure:
                            #   T1: time from old-baud 'OK<CR>' (after STBR) to banner 'STN2120 v5.6.5<CR>'
                            #   T2: time from ACK byte (<CR>) to prompt 'OK<CR><CR>>'
                            log_data, visible_bytes, hex_bytes, t_first, t_last, t_found = read_until(
                                port, TIMEOUT, command=BANNER
                            )
                            print('Received: ', visible_bytes)
                            write_log_section(log, log_data, visible_bytes, hex_bytes)

                            if BANNER in log_data:
                                t_banner = t_found if t_found is not None else t_last

                                # Send ACK immediately: EXACTLY one 0x0D byte, no extra CR appended.
                                write_log(log, "\n--- [ACK] <CR> ---")
                                t_ack_tx = monotonic()
                                port.write(b"\r")

                                # Wait for prompt OK<CR><CR>> and timestamp when it appears<CR><CR>> and timestamp when it appears
                                log_data2, visible_bytes2, hex_bytes2, tf2, tl2, tfound2 = read_until(
                                    port, TIMEOUT, command=PROMPT
                                )
                                write_log_section(log, log_data2, visible_bytes2, hex_bytes2)

                                t_prompt = None
                                if PROMPT in log_data2:
                                    t_prompt = tfound2 if tfound2 is not None else tl2

                                # Compute T1 / T2
                                if (t_ok_old is not None) and (t_banner is not None):
                                    T1_ms = (t_banner - t_ok_old) * 1000.0
                                    print(f"T1 (old OK -> banner) = {T1_ms:.3f} ms")
                                    write_log(log, f"\nT1 (old OK -> banner) = {T1_ms:.3f} ms")

                                if (t_ack_tx is not None) and (t_prompt is not None):
                                    T2_ms = (t_prompt - t_ack_tx) * 1000.0
                                    print(f"T2 (ack -> OK\\r\\r>) = {T2_ms:.3f} ms")
                                    write_log(log, f"T2 (ack -> OK\\r\\r>) = {T2_ms:.3f} ms")

                                # After successful handshake, continue with sequence
                                # SEQUENCE = [('', 0)] + SEQUENCE
                            else:
                                baud = STARTING_BAUD
                                continue
                        
                        seq = SEQUENCE[num:]
                        for cmd, delay in seq:
                            num = send_and_log(port, cmd, delay, log, num)
                            if cmd.upper().__contains__('STBRT'):
                                TIMEOUT = int([x for x in cmd.split() if x.isdigit()][0])*1.2
                            elif cmd.upper().__contains__('STBR '):
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
