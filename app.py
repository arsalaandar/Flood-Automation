import os
import secrets
import threading
import traceback
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template_string, jsonify, request,
    session, redirect, url_for
)

from auto_fetcher import check_email_and_download, run_automation, DATA_DIR


app = Flask(__name__)

# Random each process start, unless FLASK_SECRET_KEY is set - either
# way, this just signs the login session cookie so it can't be forged.
# Sessions reset (everyone logged out) whenever the app restarts if
# you don't set FLASK_SECRET_KEY explicitly in .env.
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))

APP_PASSWORD = os.environ.get("APP_PASSWORD")

if not APP_PASSWORD:

    raise RuntimeError(
        "APP_PASSWORD environment variable is not set - add it to "
        "your .env file. This is the shared password everyone will "
        "type in to access the Run All button."
    )


def login_required(view_func):

    @wraps(view_func)
    def wrapped(*args, **kwargs):

        if not session.get("logged_in"):

            return redirect(url_for("login"))

        return view_func(*args, **kwargs)

    return wrapped


# Simple in-memory job state - fine for a small handful of trusted
# users. Not thread-safe against truly concurrent triggers, but the
# "Run All" button disables itself client-side while a run is in
# progress, and the lock below prevents a second run from actually
# starting even if two people click at nearly the same moment.
state_lock = threading.Lock()

job_state = {
    "status": "idle",       # idle | running | done | error
    "log": [],
    "started_at": None,
    "finished_at": None,
}


def _log(message):

    timestamp = datetime.now().strftime("%H:%M:%S")

    line = f"[{timestamp}] {message}"

    print(line)

    job_state["log"].append(line)


def _run_job():

    try:

        job_state["status"] = "running"

        job_state["log"] = []

        job_state["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        job_state["finished_at"] = None

        _log("Checking email for new files...")

        downloaded = check_email_and_download()

        if not downloaded:

            _log("No new files found. Nothing to run.")

            job_state["status"] = "done"

            job_state["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            return

        _log(f"Found files: { {k: str(v) for k, v in downloaded.items() if v} }")

        run_automation(downloaded)

        _log("Automation run finished.")

        job_state["status"] = "done"

    except Exception:

        _log("ERROR:\n" + traceback.format_exc())

        job_state["status"] = "error"

    finally:

        job_state["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@app.route("/login", methods=["GET", "POST"])
def login():

    error = None

    if request.method == "POST":

        entered = request.form.get("password", "")

        if secrets.compare_digest(entered, APP_PASSWORD):

            session["logged_in"] = True

            return redirect(url_for("index"))

        error = "Wrong password."

    return render_template_string(LOGIN_TEMPLATE, error=error)


@app.route("/logout")
def logout():

    session.pop("logged_in", None)

    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():

    return render_template_string(PAGE_TEMPLATE)


@app.route("/run", methods=["POST"])
@login_required
def run():

    with state_lock:

        if job_state["status"] == "running":

            return jsonify({"ok": False, "message": "A run is already in progress."})

        thread = threading.Thread(target=_run_job, daemon=True)

        thread.start()

    return jsonify({"ok": True, "message": "Run started."})


@app.route("/status")
@login_required
def status():

    return jsonify(job_state)


LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Login - Flood Automation</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: system-ui, sans-serif; max-width: 360px;
               margin: 100px auto; padding: 0 16px; background: #0f1115;
               color: #e6e6e6; }
        input { font-size: 1.1rem; padding: 10px; width: 100%;
                border-radius: 6px; border: 1px solid #444;
                background: #1a1d24; color: white; margin-bottom: 12px;
                box-sizing: border-box; }
        button { font-size: 1.1rem; padding: 10px 24px; border: none;
                 border-radius: 6px; background: #2563eb; color: white;
                 cursor: pointer; width: 100%; }
        .error { color: #f87171; margin-bottom: 12px; }
    </style>
</head>
<body>
    <h2>Flood Automation</h2>
    {% if error %}<div class="error">{{ error }}</div>{% endif %}
    <form method="POST">
        <input type="password" name="password" placeholder="Password" autofocus>
        <button type="submit">Log in</button>
    </form>
</body>
</html>
"""


PAGE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Flood Automation Control</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: system-ui, sans-serif; max-width: 700px;
               margin: 40px auto; padding: 0 16px; background: #0f1115;
               color: #e6e6e6; }
        h1 { font-size: 1.4rem; }
        button { font-size: 1.1rem; padding: 14px 28px; border: none;
                 border-radius: 8px; background: #2563eb; color: white;
                 cursor: pointer; }
        button:disabled { background: #444; cursor: not-allowed; }
        #status { margin-top: 16px; font-weight: 600; }
        #log { background: #1a1d24; border-radius: 8px; padding: 12px;
               margin-top: 16px; height: 350px; overflow-y: auto;
               white-space: pre-wrap; font-family: monospace;
               font-size: 0.85rem; }
    </style>
</head>
<body>
    <h1>Flood Automation Control</h1>
    <button id="runBtn" onclick="startRun()">Run All (Check Email + Automation)</button>
    <div id="status">Status: idle</div>
    <div id="log"></div>
    <p style="margin-top:24px;"><a href="/logout" style="color:#888;">Log out</a></p>

    <script>
        let polling = null;

        function startRun() {
            fetch('/run', { method: 'POST' })
                .then(r => r.json())
                .then(data => {
                    if (!data.ok) { alert(data.message); return; }
                    document.getElementById('runBtn').disabled = true;
                    poll();
                });
        }

        function poll() {
            if (polling) clearInterval(polling);
            polling = setInterval(() => {
                fetch('/status')
                    .then(r => r.json())
                    .then(data => {
                        document.getElementById('status').innerText = 'Status: ' + data.status;
                        document.getElementById('log').innerText = data.log.join('\\n');
                        document.getElementById('log').scrollTop = document.getElementById('log').scrollHeight;
                        if (data.status !== 'running') {
                            document.getElementById('runBtn').disabled = false;
                            clearInterval(polling);
                        }
                    });
            }, 2000);
        }

        // Pick up an in-progress run if the page is reloaded mid-run
        fetch('/status').then(r => r.json()).then(data => {
            document.getElementById('status').innerText = 'Status: ' + data.status;
            document.getElementById('log').innerText = data.log.join('\\n');
            if (data.status === 'running') {
                document.getElementById('runBtn').disabled = true;
                poll();
            }
        });
    </script>
</body>
</html>
"""


if __name__ == "__main__":

    DATA_DIR.mkdir(exist_ok=True)

    app.run(host="0.0.0.0", port=5000, threaded=True)
