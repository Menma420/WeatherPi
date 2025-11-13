from flask import Flask, request, render_template_string, redirect, url_for, session, jsonify, Response
import threading, queue, json, time, os, hashlib, requests
import paho.mqtt.client as mqtt

# ---------- Config ----------
BROKER_HOST = os.getenv("BROKER_HOST", "10.147.255.200")
BROKER_PORT = int(os.getenv("BROKER_PORT", "1883"))
MQTT_TOPIC  = os.getenv("MQTT_TOPIC", "sensors/#")
SQL_API     = os.getenv("SQL_API", "https://narzee-sqlt.onrender.com/query")
SECRET_KEY  = os.getenv("SECRET_KEY", "supersecret")
MYKEY="VUSAN"
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.debug = False  # set True while debugging

# ---------- MQTT / App state ----------
clients, clients_lock = [], threading.Lock()
history, history_lock = [], threading.Lock()
latest, latest_lock   = {"temp": None, "hum": None, "pres": None, "ts": None}, threading.Lock()
MAX_HISTORY = 1000

# ---------- Utilities ----------
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def run_query(query: str):
    # lightweight log of queries (avoid logging passwords in production)
    print(f"[SQL] {query}")

def execute_sql(query: str):
    """
    Execute a remote SQL query via the SQL_API.
    If the response indicates the users table is missing, create it and retry once.
    Returns the parsed JSON response (dict) or {'error': ...} on failure.
    """
    run_query(query)
    try:
        r = requests.get(SQL_API, params={"q": query}, timeout=10)
        data = r.json()
        print("[SQL] response:", data)

        # Detect "no such table: users" (or similar) in the response and auto-create table
        msg = ""
        if isinstance(data, dict):
            msg = data.get("message") or data.get("error") or ""
        if isinstance(msg, str) and "no such table" in msg.lower() and "users" in msg.lower():
            print("[SQL] 'users' table missing — creating it now...")
            create_q = (
                "CREATE TABLE IF NOT EXISTS users ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "username TEXT UNIQUE NOT NULL, "
                "password TEXT NOT NULL"
                ");"
            )
            # attempt to create table (fire-and-forget); ignore its response
            try:
                requests.get(SQL_API, params={"q": create_q}, timeout=10)
            except Exception as e:
                print("[SQL] create table request failed:", e)
                return {"error": str(e)}
            # retry original query once
            try:
                r2 = requests.get(SQL_API, params={"q": query}, timeout=10)
                data = r2.json()
                print("[SQL] retry response:", data)
            except Exception as e:
                print("[SQL] retry failed:", e)
                return {"error": str(e)}

        return data

    except Exception as e:
        print("SQL API error:", e)
        return {"error": str(e)}
def decrypt(cipher_text, key):
    """Decrypt a value encrypted with the encrypt() function."""
    key_str = str(key)
    parts = cipher_text.split("-")
    decrypted_chars = []
    for i, val in enumerate(parts):
        decrypted_val = int(val) ^ ord(key_str[i % len(key_str)])
        decrypted_chars.append(chr(decrypted_val))
    return float("".join(decrypted_chars)) if "." in decrypted_chars else int("".join(decrypted_chars))

# ---------- Authentication routes (signup/login/logout) ----------
LOGIN_HTML = """
<!doctype html>
<html><head>
<title>Login</title>
<style>
body { font-family: sans-serif; background:#eef2f5; display:flex; justify-content:center; align-items:center; height:100vh; }
form { background:white; padding:2rem; border-radius:8px; box-shadow:0 2px 6px rgba(0,0,0,0.1); width:320px; }
input { width:100%; padding:10px; margin-bottom:10px; border:1px solid #ccc; border-radius:4px; }
button { width:100%; padding:10px; background:#0078d7; color:white; border:none; border-radius:4px; }
.error { color:red; margin-bottom:10px; text-align:center; }
a { text-decoration:none; color:#0078d7; }
</style>
</head><body>
<form method="post">
  <h3>User Login</h3>
  {% if error %}<div class="error">{{error}}</div>{% endif %}
  <input type="text" name="username" placeholder="Username" required autofocus>
  <input type="password" name="password" placeholder="Password" required>
  <button type="submit">Login</button>
  <p style="text-align:center;margin-top:10px;">New user? <a href="/signup">Sign up</a></p>
</form>
</body></html>
"""

SIGNUP_HTML = """
<!doctype html>
<html><head>
<title>Sign Up</title>
<style>
body { font-family: sans-serif; background:#eef2f5; display:flex; justify-content:center; align-items:center; height:100vh; }
form { background:white; padding:2rem; border-radius:8px; box-shadow:0 2px 6px rgba(0,0,0,0.1); width:320px; }
input { width:100%; padding:10px; margin-bottom:10px; border:1px solid #ccc; border-radius:4px; }
button { width:100%; padding:10px; background:#0078d7; color:white; border:none; border-radius:4px; }
.error { color:red; margin-bottom:10px; text-align:center; }
a { text-decoration:none; color:#0078d7; }
</style>
</head><body>
<form method="post">
  <h3>Create Account</h3>
  {% if error %}<div class="error">{{error}}</div>{% endif %}
  <input type="text" name="username" placeholder="Choose Username" required autofocus>
  <input type="password" name="password" placeholder="Choose Password" required>
  <button type="submit">Sign Up</button>
  <p style="text-align:center;margin-top:10px;">Already have an account? <a href="/login">Login</a></p>
</form>
</body></html>
"""

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if not username or not password:
            return render_template_string(SIGNUP_HTML, error="Username and password required")
        hashed = hash_password(password)

        # check if user already exists
        q_check = f"SELECT * FROM users WHERE username='{username}';"
        res_check = execute_sql(q_check)
        if res_check.get("data"):
            return render_template_string(SIGNUP_HTML, error="User already exists")

        # create user
        q_insert = f"INSERT INTO users (username, password) VALUES ('{username}', '{hashed}');"
        insert_res = execute_sql(q_insert)
        if insert_res.get("error"):
            return render_template_string(SIGNUP_HTML, error="Could not create user")
        return redirect(url_for("login"))

    return render_template_string(SIGNUP_HTML, error=None)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if not username or not password:
            return render_template_string(LOGIN_HTML, error="Username and password required")
        hashed = hash_password(password)
        q = f"SELECT * FROM users WHERE username='{username}' AND password='{hashed}';"
        result = execute_sql(q)
        print("[LOGIN] result:", result)
        ok = bool(result.get("data"))
        if ok:
            session["user"] = username
            return redirect(url_for("index"))
        else:
            return render_template_string(LOGIN_HTML, error="Invalid username or password")
    return render_template_string(LOGIN_HTML, error=None)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------- MQTT callbacks & handling ----------
def on_connect(client, userdata, flags, rc, properties=None):
    print("MQTT connected, rc:", rc)
    client.subscribe(MQTT_TOPIC, qos=1)

def on_message(client, userdata, msg):
    payload_raw = msg.payload.decode("utf-8", errors="ignore").strip()
    try:
        payload = json.loads(payload_raw)
    except Exception:
        payload = {"raw": payload_raw}

    # Extract sensors: support nested payload["value"] or flat keys
    temp = None
    hum = None
    pres = None

    if isinstance(payload.get("value"), dict):
        try:
            temp = decrypt(payload["value"].get("temperature"),MYKEY)
            hum  = decrypt(payload["value"].get("humidity"),MYKEY)
            pres = payload["value"].get("pressure")
        except Exception:
            pass

    # fallback to flat keys (if present)
    temp = temp if temp is not None else payload.get("temperature") or payload.get("temp")
    hum  = hum  if hum  is not None else payload.get("humidity") or payload.get("hum")
    pres = pres if pres is not None else payload.get("pressure") or payload.get("pres")

    # convert to floats where possible
    def to_float(x):
        try: return float(x)
        except: return None
    temp, hum, pres = map(to_float, (temp, hum, pres))

    # timestamp sanity check: if ts missing or obviously invalid (too far in future), replace with now
    ts_raw = payload.get("ts")
    try:
        ts = int(ts_raw) if ts_raw is not None else None
    except Exception:
        ts = None
    now_ms = int(time.time() * 1000)
    # if ts is None or ts is absurd (e.g., > now + 1 day), set to now
    if ts is None or ts > now_ms + 86_400_000:
        ts = now_ms

    record = {"ts": ts, "temp": temp, "hum": hum, "pres": pres, "raw": payload, "topic": msg.topic}

    with history_lock:
        history.append(record)
        if len(history) > MAX_HISTORY:
            history.pop(0)

    with latest_lock:
        if temp is not None: latest["temp"] = temp
        if hum is not None: latest["hum"] = hum
        if pres is not None: latest["pres"] = pres
        latest["ts"] = ts

    # broadcast to SSE clients (non-blocking best-effort)
    with clients_lock:
        for q in list(clients):
            try:
                q.put_nowait(record)
            except queue.Full:
                # client's queue full; drop this message for that client
                pass

def start_mqtt_loop():
    try:
        client = mqtt.Client(protocol=mqtt.MQTTv5)
        client.on_connect = on_connect
        client.on_message = on_message
        client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        client.loop_forever()
    except Exception as e:
        print("MQTT thread error:", e)

mqtt_thread = threading.Thread(target=start_mqtt_loop, daemon=True)
mqtt_thread.start()

# ---------- SSE endpoint ----------
def event_stream(q: queue.Queue):
    try:
        while True:
            msg = q.get()
            yield f"data: {json.dumps(msg)}\n\n"
    except GeneratorExit:
        return

@app.route("/stream")
def stream():
    if "user" not in session:
        return redirect(url_for("login"))
    q = queue.Queue(maxsize=200)
    with clients_lock:
        clients.append(q)
    return Response(event_stream(q), mimetype="text/event-stream")

# ---------- API endpoints for frontend ----------
@app.route("/api/history")
def api_history():
    if "user" not in session:
        return jsonify({"error": "unauthorized"}), 403
    with history_lock:
        temps = [[r["ts"], r["temp"]] for r in history if r["temp"] is not None]
        hums  = [[r["ts"], r["hum"]] for r in history if r["hum"] is not None]
        press = [[r["ts"], r["pres"]] for r in history if r["pres"] is not None]
        return jsonify({"temp": temps, "hum": hums, "pres": press})

@app.route("/api/latest")
def api_latest():
    if "user" not in session:
        return jsonify({"error": "unauthorized"}), 403
    with latest_lock:
        return jsonify(latest)

# ---------- Frontend HTML (includes luxon + chartjs-adapter-luxon) ----------
INDEX_HTML = """
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>WeatherPi Dashboard</title>
<!-- Chart.js + Luxon adapter for time axis -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script src="https://cdn.jsdelivr.net/npm/luxon@3/build/global/luxon.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-luxon@1"></script>

<style>
body{font-family:Arial;margin:12px;background:#f2f4f7}
.card{background:white;padding:12px;border-radius:8px;margin-bottom:10px;box-shadow:0 1px 4px rgba(0,0,0,0.08)}
.logout{float:right}
.meta{font-size:0.9rem;color:#555}
#raw{max-height:40vh;overflow:auto;font-family:monospace;font-size:0.9rem}
.grid{display:grid;grid-template-columns:1fr;gap:12px}
@media(min-width:900px){ .grid{grid-template-columns:1fr 1fr} }
small.note{color:#666}
</style>
</head>
<body>
<div class="card">
  <div style="display:flex;align-items:center;justify-content:space-between">
    <div>
      <h2 style="margin:.2rem 0">WeatherPi Dashboard</h2>
      <div class="meta">User: <b>{{user}}</b> &nbsp; Broker: <b>{{broker}}</b> &nbsp; Topic: <b>{{topic}}</b></div>
    </div>
    <div><a href="/logout">Logout</a></div>
  </div>
</div>

<div class="card grid">
  <div>
    <h4>Temperature (°C)</h4>
    <canvas id="chart-temp" height="160"></canvas>
  </div>
  <div>
    <h4>Humidity (%)</h4>
    <canvas id="chart-hum" height="160"></canvas>
  </div>
  <div>
    <h4>Pressure</h4>
    <canvas id="chart-pres" height="160"></canvas>
  </div>
  <div>
    <h4>Raw live stream</h4>
    <div id="raw"></div>
  </div>
</div>

<script>
const MAX_POINTS = 500;

// create chart helper (time x-axis)
function makeChart(ctx, label, color, unit){
  return new Chart(ctx, {
    type: 'line',
    data: { datasets: [{ label: label, data: [], borderColor: color, backgroundColor: color, pointRadius: 0, fill: false }]},
    options: {
      animation: false,
      parsing: false,
      scales: {
        x: {
          type: 'time',
          time: { tooltipFormat: 'HH:mm:ss', unit: 'second' }
        },
        y: {
          ticks: { callback: v => (unit ? v + ' ' + unit : v) }
        }
      },
      plugins: { legend: { display: false } },
    }
  });
}

const chartTemp = makeChart(document.getElementById('chart-temp').getContext('2d'), 'Temperature', 'rgb(220,50,50)', '°C');
const chartHum  = makeChart(document.getElementById('chart-hum').getContext('2d'), 'Humidity', 'rgb(30,120,200)', '%');
const chartPres = makeChart(document.getElementById('chart-pres').getContext('2d'), 'Pressure', 'rgb(40,180,90)', 'hPa');

function pushPoint(chart, ts, value){
  if(value === null || value === undefined) return;
  chart.data.datasets[0].data.push({x: ts, y: value});
  if(chart.data.datasets[0].data.length > MAX_POINTS) chart.data.datasets[0].data.shift();
  chart.update('none');
}

// load initial history
fetch('/api/history').then(r => r.json()).then(d => {
  if(d.temp) for(const [ts,v] of d.temp) pushPoint(chartTemp, ts, v);
  if(d.hum)  for(const [ts,v] of d.hum)  pushPoint(chartHum,  ts, v);
  if(d.pres) for(const [ts,v] of d.pres) pushPoint(chartPres, ts, v);
});

// SSE live stream
const es = new EventSource('/stream');
es.onmessage = (e) => {
  const m = JSON.parse(e.data);
  const ts = m.ts || Date.now();
  pushPoint(chartTemp, ts, m.temp);
  pushPoint(chartHum, ts, m.hum);
  pushPoint(chartPres, ts, m.pres);

  // raw log
  const raw = document.getElementById('raw');
  const pre = document.createElement('pre');
  pre.textContent = JSON.stringify(m.raw || m, null, 2);
  raw.prepend(pre);
  if(raw.children.length > 200) raw.removeChild(raw.lastChild);
};

es.onerror = (ev) => {
  console.warn("SSE error", ev);
};
</script>
</body>
</html>
"""

# ---------- Routes ----------
@app.route("/")
def index():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template_string(INDEX_HTML, broker=f"{BROKER_HOST}:{BROKER_PORT}", topic=MQTT_TOPIC, user=session["user"])

# ---------- Run server ----------
if __name__ == "__main__":
    print("Starting Flask app...")
    print("SQL_API:", SQL_API)
    print("BROKER:", BROKER_HOST, BROKER_PORT)
    app.run(host="0.0.0.0", port=5000, threaded=True)
