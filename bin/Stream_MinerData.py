from flask import Flask, Response, render_template, jsonify
import time, json, os, threading
import paramiko

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))

# Remote miner log settings
REMOTE_HOST = "10.0.0.76"
REMOTE_USER = "root"
REMOTE_PASS = "vmnr"   # ⚠️ Better: use SSH keys instead of storing password
REMOTE_LOG  = "/var/log/bllcmon.log"
LOCAL_LOG   = "data/bllcmon.log"

def stream_remote_log():
    """Continuously stream remote log into LOCAL_LOG with auto-reconnect."""
    while True:
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(REMOTE_HOST, username=REMOTE_USER, password=REMOTE_PASS, timeout=10)

            transport = ssh.get_transport()
            channel = transport.open_session()
            channel.exec_command(f"tail -90 -f {REMOTE_LOG}")

            # append instead of overwrite, so history survives restarts
            with open(LOCAL_LOG, "a", buffering=1) as outfile:
                while True:
                    if channel.recv_ready():
                        data = channel.recv(1024).decode("utf-8", errors="ignore")
                        outfile.write(data)
                    if channel.exit_status_ready():
                        raise Exception("Remote channel closed")
        except Exception as e:
            print(f"[stream_remote_log] Error: {e}. Reconnecting in 5s...")
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
    if not os.path.exists(LOCAL_LOG):
        while True:
            time.sleep(1)
            yield f"data: {json.dumps({})}\n\n"
    else:
        with open(LOCAL_LOG, "r") as f:
            f.seek(0, 2)
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.5)
                    continue
                parsed = parse_line(line)
                yield f"data: {json.dumps(parsed)}\n\n"

@app.route("/stream")
def stream():
    return Response(tail_log(), mimetype="text/event-stream")

@app.route("/init")
def init_data():
    records = read_last_n(30)
    fields = list(records[0].keys()) if records else ["Time","Status","Hash","Pwr","ITmp","OTmp","EElec","Incm"]
    return jsonify({"records": records, "fields": fields})

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    # Start background SSH log streamer
    t = threading.Thread(target=stream_remote_log, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=8080, threaded=True, debug=True)