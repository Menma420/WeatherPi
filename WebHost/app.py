from flask import Flask, request, render_template_string, redirect, url_for, session, jsonify, Response
import threading, queue, json, time, os, hashlib, requests
import paho.mqtt.client as mqtt

# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------
BROKER_HOST = os.getenv("BROKER_HOST", "172.30.148.200")
BROKER_PORT = int(os.getenv("BROKER_PORT", "1883"))
MQTT_TOPIC  = "sensors/+/+"        # subscribe to all devices & sensors
SQL_API     = os.getenv("SQL_API", "https://narzee-sqlt.onrender.com/query")
SECRET_KEY  = os.getenv("SECRET_KEY", "supersecret")
MYKEY="VUSAN"
app = Flask(__name__)
app.secret_key = SECRET_KEY

# -------------------------------------------------------------------
# GLOBALS
# -------------------------------------------------------------------
clients = []
clients_lock = threading.Lock()

history = []        # unified list
history_lock = threading.Lock()

MAX_HISTORY = 1000

latest = {
    "temp": None,
    "hum": None,
    "pres": None,
    "ts": None
}
latest_lock = threading.Lock()

# -------------------------------------------------------------------
# UTILS
# -------------------------------------------------------------------
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def run_query(q):
    print("[SQL]", q)

def execute_sql(q):
    run_query(q)
    try:
        r = requests.get(SQL_API, params={"q": q}, timeout=10)
        data = r.json()
    except:
        return {"error": "SQL request failed"}

    # Auto-create both tables if missing
    msg = (data.get("message") or data.get("error") or "").lower()

    if "no such table" in msg:
        if "users" in msg:
            requests.get(SQL_API, params={"q": """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL
                );
            """})

        if "user_data" in msg:
            requests.get(SQL_API, params={"q": """
                CREATE TABLE IF NOT EXISTS user_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    temp_sub INTEGER DEFAULT 0,
                    hum_sub INTEGER DEFAULT 0,
                    pres_sub INTEGER DEFAULT 0
                );
            """})

        # Retry original query
        r = requests.get(SQL_API, params={"q": q}, timeout=10)
        return r.json()

    return data
def decrypt(cipher_text, key):
    """Decrypt a value encrypted with the encrypt() function."""
    key_str = str(key)
    parts = cipher_text.split("-")
    decrypted_chars = []
    for i, val in enumerate(parts):
        decrypted_val = int(val) ^ ord(key_str[i % len(key_str)])
        decrypted_chars.append(chr(decrypted_val))
    return float("".join(decrypted_chars)) if "." in decrypted_chars else int("".join(decrypted_chars))
# -------------------------------------------------------------------
# AUTH PAGES
# -------------------------------------------------------------------
LOGIN_HTML = """
<!doctype html><html><head>
<title>Login</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');

:root{
  --accent-1: #0078d7;
  --accent-2: #00c2ff;
  --glass-bg: rgba(255,255,255,0.14);
  --glass-border: rgba(255,255,255,0.18);
  --muted: #e6eef6;
  --text: #0f1724;
}

* { box-sizing: border-box; }

html,body{
  height:100%;
  margin:0;
  font-family: "Inter", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial;
  color:var(--text);
  -webkit-font-smoothing:antialiased;
  -moz-osx-font-smoothing:grayscale;
}

/* full-bleed background photo + subtle animated gradient overlay */
body{
  display:flex;
  align-items:center;
  justify-content:center;
  background-color: #eaf3fb;
  background-image:
    linear-gradient(180deg, rgba(12,30,60,0.18), rgba(6,18,36,0.22)),
    url('https://images.unsplash.com/photo-1501973801540-537f08ccae7d?auto=format&fit=crop&w=1650&q=80');
  background-size:cover;
  background-position:center;
  background-attachment:fixed;
  padding:40px;
}

/* dim & blur overlay to keep text readable on small devices */
body::before{
  content:"";
  position:fixed;
  inset:0;
  background: linear-gradient(180deg, rgba(255,255,255,0.06), rgba(0,0,0,0.12));
  pointer-events:none;
  mix-blend-mode: multiply;
}

/* Form container - glass card */
form {
  width: 360px;
  max-width: calc(100% - 48px);
  background: linear-gradient(135deg, rgba(255,255,255,0.50), rgba(255,255,255,0.36));
  border-radius: 14px;
  padding: 28px 26px;
  box-shadow: 0 10px 30px rgba(8,20,40,0.35);
  border: 1px solid var(--glass-border);
  backdrop-filter: blur(10px) saturate(120%);
  -webkit-backdrop-filter: blur(10px) saturate(120%);
  display:flex;
  flex-direction:column;
  gap:10px;
  transform: translateY(0);
  transition: transform .35s cubic-bezier(.2,.9,.3,1);
}

/* subtle lift on hover/focus for desktop */
@media (hover:hover) and (pointer: fine){
  form:hover { transform: translateY(-6px); }
}

/* heading with weather glyph */
form h3{
  margin:0 0 6px 0;
  font-size:20px;
  font-weight:700;
  display:flex;
  align-items:center;
  gap:10px;
  color:#042033;
  letter-spacing:-0.2px;
}

/* add small weather badge before the heading (emoji used so no HTML changes) */
form h3::before{
  content: "🌤️";
  display:inline-block;
  font-size:20px;
  transform: translateY(1px);
}

/* error message refined */
.error {
  color:#b72b2b;
  background: rgba(183,43,43,0.06);
  border:1px solid rgba(183,43,43,0.12);
  padding:8px 10px;
  border-radius:8px;
  text-align:center;
  font-size:13px;
}

/* inputs */
input {
  width:100%;
  padding:12px 14px;
  margin:0;
  font-size:14px;
  color:#06202b;
  background: rgba(255,255,255,0.7);
  border:1px solid rgba(8,20,30,0.07);
  border-radius:10px;
  outline:none;
  transition: box-shadow .18s ease, transform .12s ease, border-color .12s ease;
  box-shadow: inset 0 -1px 0 rgba(255,255,255,0.6);
}

/* input focus look */
input:focus{
  border-color: rgba(0,120,215,0.95);
  box-shadow: 0 6px 18px rgba(0,110,200,0.12);
  transform: translateY(-1px);
}

/* placeholder subtle */
input::placeholder{
  color: rgba(6, 30, 40, 0.4);
}

/* button */
button {
  width:100%;
  padding:12px 14px;
  font-size:15px;
  font-weight:600;
  color:white;
  border-radius:10px;
  border: none;
  cursor:pointer;
  background-image: linear-gradient(90deg, var(--accent-1), var(--accent-2));
  box-shadow: 0 8px 18px rgba(0,120,215,0.18), inset 0 -2px 0 rgba(0,0,0,0.06);
  transition: transform .12s ease, box-shadow .12s ease, filter .12s ease;
}

/* button interactions */
button:hover { transform: translateY(-2px); box-shadow: 0 12px 26px rgba(0,120,215,0.20); }
button:active { transform: translateY(0); filter:brightness(.98); }

/* small sign-up line */
form p{
  margin:10px 0 0 0;
  font-size:13px;
  color: rgba(4,32,51,0.75);
  text-align:center;
}

/* link style */
form a{
  color: var(--accent-1);
  text-decoration:none;
  font-weight:600;
}
form a:hover { text-decoration:underline; }

/* responsive tweaks for very small screens */
@media (max-width:420px){
  form { padding:20px; border-radius:12px; }
  form h3 { font-size:18px; }
  input, button { padding:10px 12px; border-radius:8px; }
}

/* optional: a tiny animated cloud using a CSS keyframe on the background (subtle motion) */
@keyframes cloudFloat {
  0% { transform: translateX(-5px) translateY(0); opacity: .98; }
  50% { transform: translateX(5px) translateY(-2px); opacity: .995; }
  100% { transform: translateX(-5px) translateY(0); opacity: .98; }
}

/* apply a pseudo cloud overlay for a soft moving layer (keeps background photo readable) */
form::after{
  content:"";
  position:absolute;
  inset:auto;
  right: -40px;
  top: -40px;
  width:140px;
  height:140px;
  pointer-events:none;
  background-image: radial-gradient(circle at 30% 30%, rgba(255,255,255,0.55) 0%, rgba(255,255,255,0.25) 25%, rgba(255,255,255,0.02) 70%);
  border-radius:50%;
  filter: blur(18px);
  opacity:0.7;
  transform: translateZ(0);
  animation: cloudFloat 8s ease-in-out infinite;
}

</style></head><body>
<form method="post">
  <h3>User Login</h3>
  {% if error %}<div class="error">{{error}}</div>{% endif %}
  <input name="username" placeholder="Username" required>
  <input name="password" type="password" placeholder="Password" required>
  <button>Login</button>
  <p>New user? <a href="/signup">Sign up</a></p>
</form>
</body></html>
"""

SIGNUP_HTML = """
<!doctype html><html><head>
<title>Sign Up</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');

:root{
  --accent-1: #0078d7;
  --accent-2: #00c2ff;
  --glass-bg: rgba(255,255,255,0.14);
  --glass-border: rgba(255,255,255,0.18);
  --muted: #e6eef6;
  --text: #0f1724;
  --success: #0b9a66;
  --danger: #b72b2b;
}

* { box-sizing: border-box; }

html,body{
  height:100%;
  margin:0;
  font-family: "Inter", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial;
  color:var(--text);
  -webkit-font-smoothing:antialiased;
  -moz-osx-font-smoothing:grayscale;
}

body{
  display:flex;
  align-items:center;
  justify-content:center;
  background-color: #eaf3fb;
  background-image:
    linear-gradient(180deg, rgba(12,30,60,0.18), rgba(6,18,36,0.22)),
    url('https://images.unsplash.com/photo-1501973801540-537f08ccae7d?auto=format&fit=crop&w=1650&q=80');
  background-size:cover;
  background-position:center;
  background-attachment:fixed;
  padding:40px;
}
body::before{
  content:"";
  position:fixed;
  inset:0;
  background: linear-gradient(180deg, rgba(255,255,255,0.06), rgba(0,0,0,0.12));
  pointer-events:none;
  mix-blend-mode: multiply;
}

/* glass card */
form {
  width: 420px;
  max-width: calc(100% - 48px);
  background: linear-gradient(135deg, rgba(255,255,255,0.50), rgba(255,255,255,0.36));
  border-radius: 14px;
  padding: 28px 26px;
  box-shadow: 0 10px 30px rgba(8,20,40,0.35);
  border: 1px solid var(--glass-border);
  backdrop-filter: blur(10px) saturate(120%);
  -webkit-backdrop-filter: blur(10px) saturate(120%);
  display:flex;
  flex-direction:column;
  gap:12px;
  position:relative;
  transition: transform .35s cubic-bezier(.2,.9,.3,1);
}

/* subtle lift */
@media (hover:hover) and (pointer: fine){
  form:hover { transform: translateY(-6px); }
}

/* heading */
form h3{
  margin:0;
  font-size:20px;
  font-weight:700;
  display:flex;
  align-items:center;
  gap:10px;
  color:#042033;
  letter-spacing:-0.2px;
}
form h3::before{
  content: "🌦️";
  display:inline-block;
  font-size:20px;
  transform: translateY(1px);
}

/* error message */
.error {
  color:var(--danger);
  background: rgba(183,43,43,0.06);
  border:1px solid rgba(183,43,43,0.12);
  padding:8px 10px;
  border-radius:8px;
  text-align:center;
  font-size:13px;
}

/* inputs */
input:not([type="checkbox"]),
select {
  width:100%;
  padding:12px 14px;
  margin:0;
  font-size:14px;
  color:#06202b;
  background: rgba(255,255,255,0.78);
  border:1px solid rgba(8,20,30,0.07);
  border-radius:10px;
  outline:none;
  transition: box-shadow .18s ease, transform .12s ease, border-color .12s ease;
  box-shadow: inset 0 -1px 0 rgba(255,255,255,0.6);
}


/* focus */
input:focus, select:focus {
  border-color: rgba(0,120,215,0.95);
  box-shadow: 0 6px 18px rgba(0,110,200,0.12);
  transform: translateY(-1px);
}

/* placeholders */
input::placeholder{
  color: rgba(6, 30, 40, 0.4);
}

/* button */
button {
  width:100%;
  padding:12px 14px;
  font-size:15px;
  font-weight:600;
  color:white;
  border-radius:10px;
  border: none;
  cursor:pointer;
  background-image: linear-gradient(90deg, var(--accent-1), var(--accent-2));
  box-shadow: 0 8px 18px rgba(0,120,215,0.18), inset 0 -2px 0 rgba(0,0,0,0.06);
  transition: transform .12s ease, box-shadow .12s ease, filter .12s ease;
}

/* button interactions */
button:hover { transform: translateY(-2px); box-shadow: 0 12px 26px rgba(0,120,215,0.20); }
button:active { transform: translateY(0); filter:brightness(.98); }

/* checkbox group wrapper */
form .checkboxes {
  display:flex;
  flex-direction:column;
  gap:8px;
  margin-top:4px;
}

/* custom checkbox styling (keeps original input but hides default) */
label {
  display:flex;
  align-items:center;
  gap:10px;
  font-size:14px;
  color: rgba(4,32,51,0.85);
  cursor:pointer;
  user-select:none;
}

/* hide native checkbox but keep keyboard focusable */
label input[type="checkbox"]{
  -webkit-appearance:none;
  appearance:none;
  width:18px;
  height:18px;
  border-radius:6px;
  border:1.5px solid rgba(6,30,40,0.12);
  background: rgba(255,255,255,0.9);
  display:inline-block;
  position:relative;
  margin:0;
  outline:none;
  transition: all .12s ease;
  box-shadow: inset 0 -1px 0 rgba(255,255,255,0.6);
}

/* checked state - show a simple tick */
label input[type="checkbox"]:checked{
  background: linear-gradient(180deg, rgba(0,120,215,0.95), rgba(0,194,255,0.9));
  border-color: rgba(0,120,215,0.95);
}
label input[type="checkbox"]:checked::after{
  content: "✔";
  position:absolute;
  left:3px;
  top:-1px;
  font-size:12px;
  color:#fff;
  font-weight:700;
}

/* disabled checkbox (pressure) - visually subdued */
label input[type="checkbox"][disabled]{
  background: linear-gradient(180deg, rgba(250,250,250,0.9), rgba(245,245,245,0.9));
  border-color: rgba(6,30,40,0.06);
  cursor:not-allowed;
  opacity:0.62;
}
label input[type="checkbox"][disabled] + span,
label input[type="checkbox"][disabled] ~ span {
  opacity:0.62;
  color: rgba(6,30,40,0.45);
}

/* align small helper text for disabled */
label span.hint {
  font-size:12px;
  color: rgba(6,30,40,0.5);
}

/* small sign-up line (if any) */
form p{
  margin:6px 0 0 0;
  font-size:13px;
  color: rgba(4,32,51,0.75);
  text-align:center;
}

/* responsive */
@media (max-width:520px){
  form { width: calc(100% - 32px); padding:20px; border-radius:12px; }
  label { font-size:13px; }
  input, button { padding:10px 12px; border-radius:8px; }
}

/* decorative moving cloud (subtle) */
@keyframes cloudFloat {
  0% { transform: translateX(-6px) translateY(0); opacity: .98; }
  50% { transform: translateX(6px) translateY(-2px); opacity: .995; }
  100% { transform: translateX(-6px) translateY(0); opacity: .98; }
}
form::after{
  content:"";
  position:absolute;
  right: -36px;
  top: -36px;
  width:120px;
  height:120px;
  pointer-events:none;
  background-image: radial-gradient(circle at 30% 30%, rgba(255,255,255,0.55) 0%, rgba(255,255,255,0.25) 25%, rgba(255,255,255,0.02) 70%);
  border-radius:50%;
  filter: blur(16px);
  opacity:0.7;
  transform: translateZ(0);
  animation: cloudFloat 9s ease-in-out infinite;
}


@keyframes cloudFloat {
  0% { transform: translateX(-5px) translateY(0); opacity: .98; }
  50% { transform: translateX(5px) translateY(-2px); opacity: .995; }
  100% { transform: translateX(-5px) translateY(0); opacity: .98; }
}
form h2::before{
  content: "🌤️";
  display:inline-block;
  font-size:20px;
  transform: translateY(1px);
}


</style></head><body>
<form method="post">
  <h2>Create Account</h2>

  {% if error %}<div class="error">{{error}}</div>{% endif %}

  <input name="username" placeholder="Choose Username" required autofocus>
  <input name="password" type="password" placeholder="Choose Password" required>

  <label><input type="checkbox" name="temp_sub"> Temperature</label><br>
  <label><input type="checkbox" name="hum_sub"> Humidity</label><br>
  <label>
  <input type="checkbox" name="pres_sub" value="0" disabled>
  Pressure (Unavailable)
</label><br>


  <button>Sign Up</button>
</form>
</body></html>
"""

@app.route("/signup", methods=["GET","POST"])
def signup():
    if request.method == "POST":
        u = request.form["username"].strip()
        p = request.form["password"].strip()
        hp = hash_password(p)

        # Check user
        if execute_sql(f"SELECT * FROM users WHERE username='{u}'").get("data"):
            return render_template_string(SIGNUP_HTML, error="User already exists")

        execute_sql(f"INSERT INTO users (username, password) VALUES ('{u}', '{hp}')")

        t = 1 if request.form.get("temp_sub") else 0
        h = 1 if request.form.get("hum_sub") else 0
        pr = 1 if request.form.get("pres_sub") else 0

        execute_sql(f"""
            INSERT INTO user_data (username, temp_sub, hum_sub, pres_sub)
            VALUES ('{u}', {t}, {h}, {pr});
        """)

        return redirect("/login")

    return render_template_string(SIGNUP_HTML)

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = request.form["username"].strip()
        p = request.form["password"].strip()
        hp = hash_password(p)

        res = execute_sql(f"SELECT * FROM users WHERE username='{u}' AND password='{hp}'")
        if not res.get("data"):
            return render_template_string(LOGIN_HTML, error="Invalid username/password")

        session["user"] = u

        pref = execute_sql(f"SELECT * FROM user_data WHERE username='{u}'").get("data",[{}])[0]
        print(pref)
        session["temp_sub"] = pref[2]
        session["hum_sub"]  = pref[3]
        session["pres_sub"] = pref[4]

        return redirect("/")

    return render_template_string(LOGIN_HTML)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# -------------------------------------------------------------------
# MQTT CALLBACKS
# -------------------------------------------------------------------
def on_connect(client, userdata, flags, rc, props=None):
    print("MQTT connected")
    client.subscribe(MQTT_TOPIC)
def on_message(client, userdata, msg):
    topic_parts = msg.topic.split("/")
    # Expect: sensors/<device>/<metric>
    if len(topic_parts) != 3:
        return

    _, device_id, metric = topic_parts

    # Parse JSON payload
    try:
        data = json.loads(msg.payload.decode("utf-8"))
    except:
        print("Invalid JSON:", msg.payload)
        return

    ts = data.get("ts", int(time.time() * 1000))
    raw_value = data.get("value")

    # Default values
    temp = hum = pres = None

    # ----------------------------
    # ✔ Decrypt ONLY encrypted values
    # ----------------------------
    if metric == "temperature":
        temp = decrypt(raw_value, MYKEY) if raw_value else None

    elif metric == "humidity":
        hum = decrypt(raw_value, MYKEY) if raw_value else None

    elif metric == "pressure":
        # Pressure is NOT encrypted in your publisher
        try:
            pres = float(raw_value)
        except:
            pres = None

    # Create parsed record
    record = {
        "ts": ts,
        "temp": temp,
        "hum": hum,
        "pres": pres,
        "device": device_id,
        "raw": data
    }

    print("[MQTT Parsed]", record)

    # Store in history
    with history_lock:
        history.append(record)
        if len(history) > MAX_HISTORY:
            history.pop(0)

    # Update latest values
    with latest_lock:
        if temp is not None: latest["temp"] = temp
        if hum is not None: latest["hum"] = hum
        if pres is not None: latest["pres"] = pres
        latest["ts"] = ts

    # Broadcast to connected SSE clients
    with clients_lock:
        for q in list(clients):
            try:
                q.put_nowait(record)
            except queue.Full:
                pass


def mqtt_thread():
    c = mqtt.Client(protocol=mqtt.MQTTv5)
    c.on_connect = on_connect
    c.on_message = on_message
    c.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    c.loop_forever()

threading.Thread(target=mqtt_thread, daemon=True).start()

# -------------------------------------------------------------------
# SSE
# -------------------------------------------------------------------
def event_stream(q):
    while True:
        msg = q.get()
        yield f"data: {json.dumps(msg)}\n\n"

@app.route("/stream")
def stream():
    if "user" not in session:
        return redirect("/login")

    q = queue.Queue()
    with clients_lock:
        clients.append(q)

    return Response(event_stream(q), mimetype="text/event-stream")

# -------------------------------------------------------------------
# API
# -------------------------------------------------------------------
@app.route("/api/history")
def api_history():
    if "user" not in session:
        return jsonify({"error":"unauthorized"}),403

    temps=[]; hums=[]; press=[]
    with history_lock:
        for r in history:
            if r["temp"] is not None: temps.append([r["ts"], r["temp"]])
            if r["hum"]  is not None: hums.append([r["ts"], r["hum"]])
            if r["pres"] is not None: press.append([r["ts"], r["pres"]])

    return jsonify({"temp":temps, "hum":hums, "pres":press})

@app.route("/api/latest")
def api_latest():
    if "user" not in session:
        return jsonify({"error":"unauthorized"}),403
    with latest_lock:
        return jsonify(latest)

# -------------------------------------------------------------------
# DASHBOARD UI
# -------------------------------------------------------------------
INDEX_HTML = """
<!doctype html><html><head>
<title>WeatherPi Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdn.jsdelivr.net/npm/luxon/build/global/luxon.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-luxon"></script>

<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');

:root{
  --bg-1: #eaf3fb;
  --accent-1: #0078d7;
  --accent-2: #00c2ff;
  --glass-border: rgba(255,255,255,0.18);
  --card-shadow: rgba(8,20,40,0.14);
  --muted: #5f7887;
  --card-radius: 14px;
  --glass-elev: rgba(255,255,255,0.45);
  --surface: rgba(255,255,255,0.72);
  --success: #0b9a66;
  --danger: #b72b2b;
}

/* base */
* { box-sizing: border-box; }
html,body{height:100%; margin:0; font-family: "Inter", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial; -webkit-font-smoothing:antialiased; -moz-osx-font-smoothing:grayscale; color:#042033; background-color:var(--bg-1); }

/* full-bleed background photo with subtle overlay (matches login/signup theme) */
body{
  background-image:
    linear-gradient(180deg, rgba(12,30,60,0.12), rgba(6,18,36,0.12)),
    url('https://images.unsplash.com/photo-1501973801540-537f08ccae7d?auto=format&fit=crop&w=1650&q=80');
  background-size:cover;
  background-position:center;
  background-attachment:fixed;
  padding:20px;
}

/* page container spacing for small margins */
body > * { max-width:1200px; margin:0 auto; }

/* card */
.card{
  background: linear-gradient(135deg, var(--surface), rgba(255,255,255,0.36));
  border-radius: var(--card-radius);
  padding:18px;
  margin-bottom:16px;
  box-shadow: 0 12px 30px var(--card-shadow);
  border: 1px solid var(--glass-border);
  backdrop-filter: blur(8px) saturate(115%);
}

/* top bar card */
.card h2 { margin:0 0 6px 0; font-size:20px; display:flex; align-items:center; gap:12px; }
.card p { margin:2px 0; color:var(--muted); font-size:14px; }

/* logout link styled as a button */
.card a[href="/logout"]{
  display:inline-block;
  margin-top:8px;
  padding:8px 12px;
  border-radius:10px;
  text-decoration:none;
  font-weight:600;
  color:white;
  background-image: linear-gradient(90deg, var(--accent-1), var(--accent-2));
  box-shadow: 0 8px 18px rgba(0,120,215,0.12);
}

/* grid layout - responsive with column emphasis */
.grid{
  display:grid;
  grid-template-columns: 1fr;
  gap:14px;
  align-items:start;
}

/* on wide screens make second column share and allow main column to be wider */
@media (min-width:900px){
  .grid{ grid-template-columns: 1.2fr 0.9fr; align-items:start; }
}

/* card headings */
.card h4{ margin:0 0 10px 0; font-size:15px; color:#073047; display:flex; align-items:center; gap:8px; }

/* chart container and canvas sizing - gives charts a consistent height */
.card canvas {
  width:100% !important;
  height:200px !important;
  display:block;
  border-radius:10px;
  background: linear-gradient(180deg, rgba(255,255,255,0.02), rgba(0,0,0,0.01));
  box-shadow: inset 0 -1px 0 rgba(255,255,255,0.04);
}

/* current value styling */
.current{
  font-size:1.1rem;
  font-weight:700;
  margin-top:10px;
  color:#042033;
  display:inline-block;
  background: rgba(255,255,255,0.6);
  padding:8px 10px;
  border-radius:10px;
  border:1px solid rgba(8,20,30,0.05);
}

/* smaller muted current label if not subscribed */
.current.not {
  background: transparent;
  color:var(--muted);
  font-weight:600;
}

/* Raw stream area: monospace, scrollable, neat entries */
#raw{
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, "Roboto Mono", "Courier New", monospace;
  font-size:0.88rem;
  max-height:48vh;
  overflow:auto;
  padding:10px;
  background: rgba(2,8,16,0.02);
  border-radius:10px;
  border:1px solid rgba(8,20,30,0.04);
}

/* each pre entry style */
#raw pre{
  margin:0 0 10px 0;
  padding:8px;
  background: linear-gradient(90deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01));
  border-radius:8px;
  border:1px solid rgba(8,20,30,0.03);
  overflow:auto;
  white-space:pre-wrap;
  word-break:break-word;
}

/* small helper row for layout inside the cards if needed */
.card .row {
  display:flex;
  gap:12px;
  align-items:center;
  flex-wrap:wrap;
}

/* micro UI: tiny status badges for subscription */
.badge{
  display:inline-block;
  padding:6px 8px;
  border-radius:999px;
  font-size:12px;
  font-weight:700;
  color:white;
  background: linear-gradient(90deg, rgba(0,160,210,0.95), rgba(0,120,215,0.9));
  box-shadow: 0 6px 16px rgba(0,120,215,0.12);
}

/* unsubscribed variant */
.badge.off {
  background: transparent;
  color:var(--muted);
  border:1px dashed rgba(6,30,40,0.06);
  box-shadow:none;
  font-weight:600;
}

/* tiny caption under charts */
.card .caption {
  margin-top:8px;
  font-size:13px;
  color:var(--muted);
}

/* responsive tweaks for mobile */
@media (max-width:640px){
  .card{ padding:14px; border-radius:12px; }
  .card canvas{ height:160px !important; }
  .current{ font-size:1rem; padding:7px 8px; }
}

/* subtle appearance animation when cards load */
.card { transform: translateY(6px); opacity:0; animation: cardIn .45s cubic-bezier(.2,.9,.3,1) forwards; }
@keyframes cardIn { to { transform: translateY(0); opacity:1; } }

/* small utility: horizontal rule between dashboard sections */
.hr {
  height:1px;
  background:linear-gradient(90deg, rgba(2,8,16,0.03), rgba(2,8,16,0.02));
  margin:12px 0;
}

/* ensure tables/long JSON in raw don't overflow the layout */
.card pre, .card code { white-space:pre-wrap; word-break:break-word; }

/* focus outline improvements for accessibility */
a:focus, button:focus { outline: 3px solid rgba(0,120,215,0.12); outline-offset:3px; border-radius:8px; }

</style>

</head><body>
<div class="card">
  <h2>🌤️ WeatherPi Dashboard</h2>
  <p>User: <b>{{user}}</b></p>
  <p>Broker: {{broker}} | Topic: {{topic}}</p>
  <a href="/logout">Logout</a>
</div>

<div class="grid">

  <div class="card">
    <h4>{{ "Temperature (°C)" if temp_sub else "Temperature [NOT SUBSCRIBED]" }}</h4>
    <canvas id="temp"></canvas>
    <div id="temp-val" class="current">—</div>
  </div>

  <div class="card">
    <h4>{{ "Humidity (%)" if hum_sub else "Humidity [NOT SUBSCRIBED]" }}</h4>
    <canvas id="hum"></canvas>
    <div id="hum-val" class="current">—</div>
  </div>

  <div class="card">
    <h4>{{ "Pressure (hPa)" if pres_sub else "Pressure [NOT SUBSCRIBED]" }}</h4>
    <canvas id="pres"></canvas>
    <div id="pres-val" class="current">—</div>
  </div>

  <div class="card">
    <h4>Raw Stream</h4>
    <div id="raw"></div>
  </div>

</div>

<script>
const tempChart = new Chart(document.getElementById("temp"), {
    type:"line", data:{datasets:[{data:[], borderColor:"red"}]},
    options:{animation:false, parsing:false,plugins: { legend: { display: false } },
      scales:{x:{type:"time", time:{unit:"second"}}}}
});
const humChart = new Chart(document.getElementById("hum"), {
    type:"line", data:{datasets:[{data:[], borderColor:"blue"}]},
    options:{animation:false, parsing:false,parsing:false,plugins: { legend: { display: false } },
      scales:{x:{type:"time", time:{unit:"second"}}}}
});
const presChart = new Chart(document.getElementById("pres"), {
    type:"line", data:{datasets:[{data:[], borderColor:"green"}]},
    options:{animation:false, parsing:false,parsing:false,plugins: { legend: { display: false } },
      scales:{x:{type:"time", time:{unit:"second"}}}}
});

function push(chart,ts,val){
  if(val==null) return;
  chart.data.datasets[0].data.push({x:ts,y:val});
  if(chart.data.datasets[0].data.length>500)
     chart.data.datasets[0].data.shift();
  chart.update("none");
}

fetch("/api/history").then(r=>r.json()).then(d=>{
    {% if temp_sub %} d.temp.forEach(v=>push(tempChart,v[0],v[1])); {% endif %}
    {% if hum_sub %}  d.hum.forEach(v=>push(humChart,v[0],v[1])); {% endif %}
    {% if pres_sub %} d.pres.forEach(v=>push(presChart,v[0],v[1])); {% endif %}
});

const es = new EventSource("/stream");

es.onmessage = e=>{
    const m = JSON.parse(e.data);

    {% if temp_sub %}
    if(m.temp!=null) {
        push(tempChart, m.ts, m.temp);
        document.getElementById("temp-val").textContent = m.temp + " °C";
    }
    {% else %}
    document.getElementById("temp-val").textContent = "Not subscribed";
    {% endif %}

    {% if hum_sub %}
    if(m.hum!=null) {
        push(humChart, m.ts, m.hum);
        document.getElementById("hum-val").textContent = m.hum + " %";
    }
    {% else %}
    document.getElementById("hum-val").textContent = "Not subscribed";
    {% endif %}

    {% if pres_sub %}
    if(m.pres!=null) {
        push(presChart, m.ts, m.pres);
        document.getElementById("pres-val").textContent = m.pres;
    }
    {% else %}
    document.getElementById("pres-val").textContent = "Not subscribed";
    {% endif %}

    const raw=document.getElementById("raw");
    const pre=document.createElement("pre");
    pre.textContent = JSON.stringify(m.raw,null,2);
    raw.prepend(pre);
    if(raw.children.length>200) raw.removeChild(raw.lastChild);
};
</script>

</body></html>
"""

# -------------------------------------------------------------------
# MAIN PAGE
# -------------------------------------------------------------------
@app.route("/")
def index():
    if "user" not in session:
        return redirect("/login")

    return render_template_string(
        INDEX_HTML,
        user=session["user"],
        broker=f"{BROKER_HOST}:{BROKER_PORT}",
        topic=MQTT_TOPIC,
        temp_sub=session.get("temp_sub",0),
        hum_sub=session.get("hum_sub",0),
        pres_sub=session.get("pres_sub",0),
    )

# -------------------------------------------------------------------
# RUN SERVER
# -------------------------------------------------------------------
if __name__ == "__main__":
    print("WeatherPi started")
    app.run(host="0.0.0.0", port=5000, threaded=True)
