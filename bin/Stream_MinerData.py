from flask import Flask, Response, render_template, jsonify
import time, json, os, threading, signal, sys
import paramiko

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))

# Remote miner log settings
REMOTE_HOST = "10.0.0.76"
REMOTE_USER = "root"
REMOTE_PASS = "vmnr"   # Consider SSH keys for production
REMOTE_LOG  = "/var/log/bllcmon.log"
LOCAL_LOG   = os.path.join(BASE_DIR, "data", "bllcmon.log")

# Globals for cleanup
ssh = None
channel = None

# Web server settings
host = "0.0.0.0"
port = 8080
number_of_data_points = 180  # Number of data points to fetch on init 720 for 1 day

# Ensure local dir exists
os.makedirs(os.path.dirname(LOCAL_LOG), exist_ok=True)

def stream_remote_log():
    """
    Single remote tail: send last $number_of_data_points lines, then follow.
    Writes to LOCAL_LOG. Auto-reconnect on errors.
    """
    global ssh, channel
    while True:
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(REMOTE_HOST, username=REMOTE_USER, password=REMOTE_PASS, timeout=10)

            transport = ssh.get_transport()
            transport.set_keepalive(30)
            channel = transport.open_session()
            channel.get_pty()  # ensures remote tail dies when session closes
            # ONE command: history + live
            channel.exec_command(f"tail -n {number_of_data_points} -f {REMOTE_LOG}")

            with open(LOCAL_LOG, "a", buffering=1) as outfile:
                while True:
                    if channel.recv_ready():
                        data = channel.recv(4096).decode("utf-8", errors="ignore")
                        if data:
                            outfile.write(data)
                    # If remote command ends, reconnect
                    if channel.exit_status_ready():
                        raise Exception("Remote channel closed")
                    time.sleep(0.05)
        except Exception as e:
            print(f"[stream_remote_log] Error: {e}. Reconnecting in 5s...")
            # Close any stale resources before reconnecting
            try:
                if channel:
                    channel.close()
                if ssh:
                    ssh.close()
            except:
                pass
            time.sleep(5)
            continue

def parse_line(line: str):
    parts = {}
    fields = line.strip().split("|")
    if not fields or not fields[0]:
        return {}
    parts["Time"] = fields[0]
    for item in fields[1:]:
        if ":" in item:
            k, v = item.split(":", 1)
            parts[k.strip()] = v.strip()
    return parts

def read_last_n(n: int):
    if not os.path.exists(LOCAL_LOG):
        return []
    with open(LOCAL_LOG, "r") as f:
        lines = [ln for ln in f.readlines() if ln.strip()]
    tail = lines[-n:] if len(lines) > n else lines
    return [parse_line(ln) for ln in tail if parse_line(ln)]

def tail_log():
    """
    Server-Sent Events: start at end-of-file, stream only NEW lines.
    Prevents duplication of the 90-line history returned by /init.
    """
    if not os.path.exists(LOCAL_LOG):
        # idle until local log appears
        while True:
            time.sleep(1)
            yield f"data: {json.dumps({})}\n\n"
    else:
        with open(LOCAL_LOG, "r") as f:
            f.seek(0, 2)  # jump to EOF, so we don't resend history
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.25)
                    continue
                parsed = parse_line(line)
                if parsed:
                    yield f"data: {json.dumps(parsed)}\n\n"

@app.route("/stream")
def stream():
    return Response(tail_log(), mimetype="text/event-stream")

@app.route("/init")
def init_data():
    # Return a snapshot of last number_of_data_points rows
    records = read_last_n(number_of_data_points)
    fields = list(records[0].keys()) if records else ["Time","Status","Hash","Pwr","ITmp","OTmp","EElec","Incm"]
    return jsonify({"records": records, "fields": fields})

@app.route("/")
def index():
    return render_template("index.html")

def cleanup(sig=None, frame=None):
    """Cleanly terminate remote tail and SSH on exit."""
    global ssh, channel
    print("Cleaning up SSH session...")
    try:
        if channel:
            channel.close()
        if ssh:
            ssh.close()
    except:
        pass
    sys.exit(0)

if __name__ == "__main__":
    # Handle Ctrl-C / kill cleanly
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Start single background SSH tail (history + live)
    t = threading.Thread(target=stream_remote_log, daemon=True)
    t.start()

    # IMPORTANT: Disable Flask reloader to avoid spawning multiple threads/processes
    app.run(host, port, threaded=True, debug=False, use_reloader=False)