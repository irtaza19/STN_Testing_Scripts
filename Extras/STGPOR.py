# ===== CONFIG =====
PORT                = "COM8"
BAUD                = 9600
TX_NEWLINE          = "\r"

COMMAND             = "STGPOR"
START               = 0
END                 = 45
COMMAND_DELAY       = 1

BASE_DELAY          = 1
ATZ_DELAY           = 2
ATD_DELAY           = 2
STRSTNVM_DELAY      = 3

IDLE_GAP_SEC        = 0.3                       # stop reading after this much quiet time
READ_SLICE_SLEEP    = 0.04                      # check serial port for new data after this much time

# ===== SEQUENCE =====                          # STRSTNVM will run automatically in the beginning and end
SEQUENCE = [					                # ATPP commands will run automatically before every sequence
    # ("strstnvm",   STRSTNVM_DELAY),
]

from serial     import Serial
from time       import sleep, time
from datetime   import datetime
from os.path    import abspath, basename, splitext

# ===== HELPERS =====
def write_log(f, text: str):
    f.write(text + ("\n" if not text.endswith("\n") else ""))

def send_and_log(ser: Serial, cmd: str, delay: float, log, num: int):
    """Send one command, wait, read response, and log everything."""
    write_log(log, f"\n--- [{num}] {cmd} ---")
    print(f"[{num}] {cmd}")

    cmd += TX_NEWLINE
    cmd_b = cmd.encode("ascii", errors="ignore")
    
    # Flush any stale bytes before sending a command.
    sleep(0.05)
    ser.reset_input_buffer()

    ser.write(cmd_b)
    sleep(delay)

    # Keep reading until the device is quiet for IDLE_GAP_SEC.
    buf = bytearray()
    last_rx = time()
    while True:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
            last_rx = time()
            sleep(READ_SLICE_SLEEP)
        elif (time() - last_rx) >= IDLE_GAP_SEC:
            break
        else:
            sleep(READ_SLICE_SLEEP)
    log_data = bytes(buf)

    # Replace invisible bytes with text
    hex_bytes = " ".join(f"{x:02X}" for x in log_data)
    chars = []
    for x in log_data:
        if   x == 0x20:         chars.append("·")
        elif x == 0xd:          chars.append("<CR>")
        elif x == 0xa:          chars.append("<LF>\n")
        elif x == 0x9:          chars.append("<TAB>")
        elif 0x21 <= x <= 0x7E: chars.append(chr(x))
        else:                   chars.append(f"\\x{x:02X}")
    visible_bytes = "".join(chars)

    write_log(log, f"len={len(log_data)}\n{visible_bytes}\nHEX: {hex_bytes}")
    return num + 1

# ===== MAIN =====
def main():
    for _ in range(1):
        LOG_FILE = f"{COMMAND} from {START} to {END}.txt"
        print(f"Opening PORT = {PORT} @ Baud = {BAUD} …")

        try:
            with Serial(PORT, baudrate=BAUD, timeout=0) as port, open(LOG_FILE, "w", encoding="utf-8") as log:
                write_log(log, f"=== SEQUENCE TEST ===\nStarted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nPORT = {PORT} @ Baud = {BAUD}")
                print(f"Log file: {abspath(LOG_FILE)}")

                sleep(3) # initial delay

                num = send_and_log(port, "STRSTNVM", STRSTNVM_DELAY, log, 0)

                for num in range(START, END + 1):
                    num = send_and_log(port, f"{COMMAND} {num}", COMMAND_DELAY, log, num)

                for cmd, delay in SEQUENCE:
                    num = send_and_log(port, cmd, delay, log, num)

                send_and_log(port, "STRSTNVM", STRSTNVM_DELAY, log, num)

        except Exception as e:
            print(f"❌ Error: {e}")
            return

        print(f"\n✅ Done. Log saved to: {abspath(LOG_FILE)}")

# ===== ENTRYPOINT =====
if __name__ == "__main__":
    main()
