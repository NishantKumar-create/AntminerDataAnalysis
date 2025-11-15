from flask import Flask, Response, render_template, jsonify, request
import time, json, os, signal, sys, requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))

# Google Drive log settings
DRIVE_FILE_ID = "1BGwJx8DDQiz0H9ddujdRmpg0FRYaXnwB"
DRIVE_URL = f"https://drive.google.com/uc?export=download&id={DRIVE_FILE_ID}"
LOCAL_LOG   = os.path.join(BASE_DIR, "data", "bllcmon.log")

# Web server settings
host = "0.0.0.0"
port = 8080
number_of_data_points = 180  # snapshot size

# Track last line index globally
last_line_index = 0

os.makedirs(os.path.dirname(LOCAL_LOG), exist_ok=True)

def fetch_drive_log():
    """Download the log file from Google Drive and overwrite LOCAL_LOG."""
    try:
        r = requests.get(DRIVE_URL, stream=True)
        if r.status_code == 200:
            with open(LOCAL_LOG, "wb") as f:
                for chunk in r.iter_content(1024):
                    f.write(chunk)
        else:
            print(f"[fetch_drive_log] Error {r.status_code} fetching file")
    except Exception as e:
        print(f"[fetch_drive_log] Exception: {e}")

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

def get_new_records(last_seen_index: int):
    """Return only new records since last_seen_index."""
    fetch_drive_log()  # refresh file from Drive

    if not os.path.exists(LOCAL_LOG):
        return [], last_seen_index

    with open(LOCAL_LOG, "r") as f:
        lines = [ln for ln in f.readlines() if ln.strip()]

    new_lines = lines[last_seen_index:]
    new_index = len(lines)

    records = [parse_line(ln) for ln in new_lines if parse_line(ln)]
    return records, new_index

def tail_log(start_index):
    """SSE stream: yield only new records incrementally, starting from start_index."""
    global last_line_index
    last_line_index = start_index

    while True:
        new_records, new_index = get_new_records(last_line_index)
        for rec in new_records:
            yield f"id: {last_line_index}\ndata: {json.dumps(rec)}\n\n"
            last_line_index += 1
        time.sleep(2)  # poll every 2s

@app.route("/stream")
def stream():
    # Capture Last-Event-ID while request context is active
    last_event_id = request.headers.get("Last-Event-ID")
    try:
        start_index = int(last_event_id) if last_event_id else last_line_index
    except ValueError:
        start_index = last_line_index

    return Response(tail_log(start_index), mimetype="text/event-stream")

@app.route("/new")
def new_data():
    global last_line_index
    records, new_index = get_new_records(last_line_index)
    last_line_index = new_index
    return jsonify({"records": records})

@app.route("/init")
def init_data():
    """Return a snapshot of last N rows for initial load."""
    fetch_drive_log()
    if not os.path.exists(LOCAL_LOG):
        return jsonify({"records": [], "fields": []})

    with open(LOCAL_LOG, "r") as f:
        lines = [ln for ln in f.readlines() if ln.strip()]

    tail = lines[-number_of_data_points:] if len(lines) > number_of_data_points else lines
    records = [parse_line(ln) for ln in tail if parse_line(ln)]
    fields = list(records[0].keys()) if records else ["Time","Status","Hash","Pwr","ITmp","OTmp","EElec","Incm"]

    # Update last_line_index to end of file
    global last_line_index
    last_line_index = len(lines)

    return jsonify({"records": records, "fields": fields})

@app.route("/")
def index():
    return render_template("index.html")

def cleanup(sig=None, frame=None):
    print("Cleaning up...")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    app.run(host, port, threaded=True, debug=False, use_reloader=False)