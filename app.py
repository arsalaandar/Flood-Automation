import os
import secrets
import threading
import traceback
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import (
    Flask, render_template_string, jsonify, request,
    session, redirect, url_for
)

from auto_fetcher import check_email_and_download, run_automation, DATA_DIR

app = Flask(__name__)

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

state_lock = threading.Lock()

job_state = {
    "status": "idle",
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

        _log("Initializing automation sequence...")
        _log("Checking email for new files...")

        downloaded = check_email_and_download()
        if not downloaded:
            _log("No new files found in email.")
            # Initialize as empty dict so we can add local files to it
            downloaded = {"kashmir": None, "jammu": None, "rainfall": None}
        else:
            _log(f"Found files in email: { {k: str(v) for k, v in downloaded.items() if v} }")

        # Also scan local data/ folder for any manually uploaded or leftover files
        local_files = list(DATA_DIR.iterdir())
        if local_files:
            _log(f"Scanning local data/ folder... Found {len([f for f in local_files if f.is_file()])} file(s).")
            for f in local_files:
                if not f.is_file(): continue
                ext = f.suffix.lower()
                if ext == ".txt" and f.name == "whatsapp.txt":
                    downloaded["kashmir"] = f
                elif ext in [".xls", ".xlsx"]:
                    if "rainfall" in f.name.lower() or "mkformat" in f.name.lower():
                        downloaded["rainfall"] = f
                    else:
                        downloaded["jammu"] = f
                elif ext in [".pdf", ".png", ".jpg", ".jpeg"]:
                    downloaded["jammu"] = f

        if not any(downloaded.values()):
            _log("No files to process (email empty, data/ empty). Nothing to run.")
            job_state["status"] = "done"
            job_state["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return

        run_automation(downloaded, log_callback=_log)

        _log("✅ Automation run finished successfully.")
        job_state["status"] = "done"

    except Exception:
        _log("❌ ERROR:\n" + traceback.format_exc())
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
        error = "Wrong password. Please try again."
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

# ==========================================================
# FILE MANAGER ROUTES
# ==========================================================

@app.route("/api/files")
@login_required
def get_files():
    waiting = []
    if DATA_DIR.exists():
        for f in DATA_DIR.iterdir():
            if f.is_file():
                waiting.append(f.name)
                
    processed = []
    processed_dir = DATA_DIR / "processed"
    if processed_dir.exists():
        for day_dir in sorted(processed_dir.iterdir(), reverse=True):
            if day_dir.is_dir():
                for f in day_dir.iterdir():
                    if f.is_file():
                        processed.append(f"{day_dir.name}/{f.name}")
                        
    return jsonify({"waiting": waiting, "processed": processed[:20]})

@app.route("/api/upload", methods=["POST"])
@login_required
def upload_files():
    if 'files' not in request.files:
        return jsonify({"ok": False, "message": "No files part"}), 400
        
    files = request.files.getlist('files')
    DATA_DIR.mkdir(exist_ok=True)
    
    saved = 0
    for file in files:
        if file.filename:
            safe_name = "".join(c for c in file.filename if c.isalnum() or c in (' ', '.', '_', '-')).rstrip()
            if safe_name.lower().endswith(".txt"):
                safe_name = "whatsapp.txt"
                
            filepath = DATA_DIR / safe_name
            file.save(filepath)
            saved += 1
            
    return jsonify({"ok": True, "message": f"Uploaded {saved} file(s) successfully."})

@app.route("/api/delete", methods=["POST"])
@login_required
def delete_file():
    data = request.json
    filename = data.get("filename", "")
    file_type = data.get("type", "")
    
    if not filename:
        return jsonify({"ok": False, "message": "No filename provided"}), 400

    # Security: Prevent path traversal (e.g. ../../etc/passwd)
    # We split the filename and only take the actual base name(s)
    parts = [p for p in filename.replace('\\', '/').split('/') if p not in ('', '.', '..')]
    
    if file_type == "waiting":
        if len(parts) != 1:
            return jsonify({"ok": False, "message": "Invalid filename"}), 400
        target = DATA_DIR / parts[0]
    elif file_type == "processed":
        if len(parts) != 2:
            return jsonify({"ok": False, "message": "Invalid processed path"}), 400
        target = DATA_DIR / "processed" / parts[0] / parts[1]
    else:
        return jsonify({"ok": False, "message": "Invalid type"}), 400

    # Final safety check: ensure the resolved path is still inside DATA_DIR
    try:
        target.resolve().relative_to(DATA_DIR.resolve())
    except ValueError:
        return jsonify({"ok": False, "message": "Access denied"}), 403

    if target.exists() and target.is_file():
        try:
            target.unlink()
            return jsonify({"ok": True, "message": f"Deleted {parts[-1]}"})
        except Exception as e:
            return jsonify({"ok": False, "message": str(e)}), 500
    else:
        return jsonify({"ok": False, "message": "File not found"}), 404

# ==========================================================
# PREMIUM UI TEMPLATES
# ==========================================================

LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Login - Flood Automation</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Inter', sans-serif; background: #0b1120; color: #f8fafc; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; overflow: hidden; }
        /* Animated background glow */
        .glow { position: fixed; width: 600px; height: 600px; background: radial-gradient(circle, rgba(37, 99, 235, 0.15) 0%, rgba(11, 17, 32, 0) 70%); top: -200px; left: -200px; z-index: 0; animation: float 8s ease-in-out infinite; }
        .glow-2 { position: fixed; width: 500px; height: 500px; background: radial-gradient(circle, rgba(16, 185, 129, 0.1) 0%, rgba(11, 17, 32, 0) 70%); bottom: -150px; right: -150px; z-index: 0; animation: float 10s ease-in-out infinite reverse; }
        @keyframes float { 0%, 100% { transform: translate(0, 0); } 50% { transform: translate(50px, 50px); } }

        .card { position: relative; z-index: 1; background: rgba(30, 41, 59, 0.6); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); padding: 48px 40px; border-radius: 24px; box-shadow: 0 20px 50px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.1); width: 100%; max-width: 420px; text-align: center; border: 1px solid rgba(255, 255, 255, 0.1); }
        .logo { font-size: 2.5rem; margin-bottom: 16px; }
        .card h2 { margin: 0 0 8px 0; color: #fff; font-size: 1.8rem; font-weight: 700; letter-spacing: -0.5px; }
        .card p { color: #94a3b8; font-size: 14px; margin-bottom: 32px; }
        input { width: 100%; padding: 16px; margin-bottom: 16px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.1); background: rgba(15, 23, 42, 0.8); color: #fff; box-sizing: border-box; font-size: 16px; transition: all 0.2s; }
        input:focus { outline: none; border-color: #3b82f6; box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.2); }
        button { width: 100%; padding: 16px; border-radius: 12px; border: none; background: linear-gradient(135deg, #3b82f6, #2563eb); color: white; font-size: 16px; font-weight: 600; cursor: pointer; transition: all 0.2s; box-shadow: 0 4px 15px rgba(37, 99, 235, 0.4); }
        button:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(37, 99, 235, 0.6); }
        button:active { transform: translateY(0); }
        .error { color: #f87171; margin-bottom: 16px; font-size: 14px; background: rgba(248, 113, 113, 0.1); padding: 10px; border-radius: 8px; border: 1px solid rgba(248, 113, 113, 0.2); }
        .footer { margin-top: 32px; font-size: 12px; color: #64748b; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 20px; letter-spacing: 0.5px; }
    </style>
</head>
<body>
    <div class="glow"></div>
    <div class="glow-2"></div>
    <div class="card">
        <div class="logo">🌊</div>
        <h2>Flood Automation</h2>
        <p>Secure Access Required</p>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="POST">
            <input type="password" name="password" placeholder="Enter Password" autofocus>
            <button type="submit">Unlock Dashboard</button>
        </form>
        <div class="footer">DESIGNED BY ARSALAAN DAR</div>
    </div>
</body>
</html>
"""

PAGE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Flood Automation Control</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root { --bg: #0b1120; --card-bg: rgba(30, 41, 59, 0.6); --border: rgba(255, 255, 255, 0.1); --text: #e2e8f0; --text-muted: #94a3b8; --primary: #3b82f6; --success: #10b981; }
        body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 0; min-height: 100vh; display: flex; flex-direction: column; }
        
        /* Header */
        .header { background: rgba(11, 17, 32, 0.8); backdrop-filter: blur(12px); padding: 18px 32px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); position: sticky; top: 0; z-index: 100; }
        .header h1 { margin: 0; font-size: 1.3rem; color: #fff; letter-spacing: -0.5px; display: flex; align-items: center; gap: 12px; }
        .header .brand { font-size: 0.75rem; color: var(--text-muted); background: rgba(255,255,255,0.05); padding: 8px 14px; border-radius: 20px; border: 1px solid var(--border); letter-spacing: 0.5px; text-transform: uppercase; font-weight: 500; }
        
        /* Layout */
        .container { max-width: 1000px; margin: 40px auto; padding: 0 24px; flex-grow: 1; width: 100%; box-sizing: border-box; display: grid; gap: 28px; }
        
        /* Glass Cards */
        .card { background: var(--card-bg); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); padding: 28px; border-radius: 20px; border: 1px solid var(--border); box-shadow: 0 8px 32px rgba(0,0,0,0.2); }
        .card-title { margin: 0 0 20px 0; color: var(--text-muted); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1.5px; display: flex; justify-content: space-between; align-items: center; font-weight: 600; }
        
        /* Controls */
        .controls { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 20px; }
        .btn-run { background: linear-gradient(135deg, var(--primary), var(--success)); color: white; border: none; padding: 16px 36px; font-size: 1.1rem; border-radius: 12px; cursor: pointer; font-weight: 600; transition: all 0.3s ease; box-shadow: 0 4px 20px rgba(59, 130, 246, 0.3); display: flex; align-items: center; gap: 10px; }
        .btn-run:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 8px 25px rgba(59, 130, 246, 0.5); }
        .btn-run:disabled { background: #475569; cursor: not-allowed; box-shadow: none; transform: none; opacity: 0.7; }
        
        /* Status Badge */
        .status-badge { padding: 10px 18px; border-radius: 12px; font-weight: 600; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px; display: flex; align-items: center; gap: 10px; }
        .status-badge::before { content: ''; width: 8px; height: 8px; border-radius: 50%; background: currentColor; box-shadow: 0 0 10px currentColor; }
        .status-idle { background: rgba(148, 163, 184, 0.1); color: #94a3b8; }
        .status-running { background: rgba(59, 130, 246, 0.15); color: #60a5fa; animation: pulse 1.5s infinite; }
        .status-done { background: rgba(16, 185, 129, 0.15); color: #4ade80; }
        .status-error { background: rgba(239, 68, 68, 0.15); color: #f87171; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.6; } 100% { opacity: 1; } }

        /* File Manager */
        .file-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
        @media (max-width: 768px) { .file-grid { grid-template-columns: 1fr; } .header { padding: 15px 20px; } .header .brand { display: none; } }
        .file-col-header { font-size: 0.75rem; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }
        .col-waiting { color: #60a5fa; }
        .col-processed { color: #4ade80; }
        
        .file-list { background: rgba(15, 23, 42, 0.6); border-radius: 12px; padding: 14px; height: 140px; overflow-y: auto; font-size: 0.85rem; color: #cbd5e1; font-family: 'JetBrains Mono', monospace; border: 1px solid rgba(255,255,255,0.05); }
        .file-item { padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.03); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: flex; justify-content: space-between; align-items: center; }
        .file-item:last-child { border-bottom: none; }
        .file-list::-webkit-scrollbar { width: 6px; } 
        .file-list::-webkit-scrollbar-thumb { background: #334155; border-radius: 10px; }
        
        .btn-del { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); padding: 2px 6px; border-radius: 4px; cursor: pointer; font-size: 10px; flex-shrink: 0; transition: 0.2s; }
        .btn-del:hover { background: rgba(239, 68, 68, 0.4); color: #fff; }
        
        /* Drop Zone */
        .drop-zone { margin-top: 20px; border: 2px dashed rgba(255,255,255,0.1); border-radius: 12px; padding: 24px; text-align: center; color: var(--text-muted); cursor: pointer; transition: all 0.2s; background: rgba(15, 23, 42, 0.4); }
        .drop-zone:hover, .drop-zone.dragover { border-color: var(--primary); background: rgba(59, 130, 246, 0.05); color: #fff; }
        .drop-zone input { display: none; }
        .drop-zone p { margin: 0; font-size: 14px; font-weight: 500; }
        .upload-status { margin-top: 10px; font-size: 13px; color: var(--success); font-weight: 500; }

        /* Terminal */
        .terminal-window { background: rgba(0, 0, 0, 0.4); backdrop-filter: blur(12px); border-radius: 16px; border: 1px solid var(--border); overflow: hidden; box-shadow: 0 10px 40px rgba(0,0,0,0.4); }
        .terminal-header { background: rgba(15, 23, 42, 0.8); padding: 12px 18px; display: flex; align-items: center; border-bottom: 1px solid var(--border); }
        .dot { width: 12px; height: 12px; border-radius: 50%; margin-right: 8px; box-shadow: 0 0 5px currentColor; }
        .dot-red { background: #ef4444; color: #ef4444; } .dot-yellow { background: #eab308; color: #eab308; } .dot-green { background: #22c55e; color: #22c55e; }
        .terminal-title { margin-left: auto; font-size: 12px; color: var(--text-muted); font-family: 'JetBrains Mono', monospace; }
        
        #log { padding: 24px; height: 420px; overflow-y: auto; font-family: 'JetBrains Mono', monospace; font-size: 0.9rem; color: #22c55e; white-space: pre-wrap; line-height: 1.7; }
        #log::-webkit-scrollbar { width: 8px; } 
        #log::-webkit-scrollbar-track { background: transparent; }
        #log::-webkit-scrollbar-thumb { background: #334155; border-radius: 10px; }
        
        /* Footer */
        .footer { text-align: center; padding: 30px; color: var(--text-muted); font-size: 0.85rem; border-top: 1px solid var(--border); background: rgba(11, 17, 32, 0.5); }
        .footer a { color: var(--primary); text-decoration: none; font-weight: 500; }
        .footer strong { color: #cbd5e1; letter-spacing: 0.5px; }
        
        .btn-sm { background: rgba(255,255,255,0.05); color: var(--text-muted); border: 1px solid var(--border); padding: 6px 12px; border-radius: 8px; font-size: 12px; cursor: pointer; transition: all 0.2s; font-weight: 500; }
        .btn-sm:hover { background: rgba(255,255,255,0.1); color: #fff; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🌊 JK Flood Automation</h1>
        <div class="brand">Arsalaan Dar</div>
    </div>
    
    <div class="container">
        <!-- Control Center -->
        <div class="card controls">
            <button id="runBtn" class="btn-run" onclick="startRun()">⚡ Run All Automations</button>
            <div id="status" class="status-badge status-idle">Idle</div>
        </div>
        
        <!-- File Manager -->
        <div class="card">
            <div class="card-title">
                <span>📁 File Manager</span>
                <button class="btn-sm" onclick="loadFiles()">Refresh</button>
            </div>
            <div class="file-grid">
                <div>
                    <div class="file-col-header col-waiting">Waiting in data/ (Will Run Next)</div>
                    <div id="waitingList" class="file-list">Loading...</div>
                </div>
                <div>
                    <div class="file-col-header col-processed">Recently Processed</div>
                    <div id="processedList" class="file-list">Loading...</div>
                </div>
            </div>
            <label class="drop-zone" id="dropZone">
                <input type="file" id="fileInput" multiple>
                <p>📎 Drag & Drop files here or click to upload</p>
                <div id="uploadStatus" class="upload-status"></div>
            </label>
        </div>
        
        <!-- Terminal -->
        <div class="terminal-window">
            <div class="terminal-header">
                <div class="dot dot-red"></div>
                <div class="dot dot-yellow"></div>
                <div class="dot dot-green"></div>
                <div class="terminal-title">automation_logs@aws-mumbai</div>
            </div>
            <div id="log">Waiting for command... Click "Run All" to start.</div>
        </div>
    </div>
    
    <div class="footer">
        <p><strong>MADE BY ARSALAAN DAR</strong> • POWERED BY AWS MUMBAI • PLAYWRIGHT AUTOMATION</p>
        <p style="margin-top:10px;"><a href="/logout">Log out</a></p>
    </div>

    <script>
        let polling = null;

        function updateStatusUI(status) {
            const statusEl = document.getElementById('status');
            statusEl.className = 'status-badge status-' + status.toLowerCase();
            statusEl.innerText = status.charAt(0).toUpperCase() + status.slice(1);
        }

        function startRun() {
            fetch('/run', { method: 'POST' })
                .then(r => r.json())
                .then(data => {
                    if (!data.ok) { alert(data.message); return; }
                    document.getElementById('runBtn').disabled = true;
                    document.getElementById('log').innerText = '';
                    poll();
                });
        }

        function poll() {
            if (polling) clearInterval(polling);
            polling = setInterval(() => {
                fetch('/status')
                    .then(r => r.json())
                    .then(data => {
                        updateStatusUI(data.status);
                        document.getElementById('log').innerText = data.log.join('\\n');
                        document.getElementById('log').scrollTop = document.getElementById('log').scrollHeight;
                        if (data.status !== 'running') {
                            document.getElementById('runBtn').disabled = false;
                            clearInterval(polling);
                            loadFiles();
                        }
                    });
            }, 1000);
        }

        function loadFiles() {
            fetch('/api/files')
                .then(r => r.json())
                .then(data => {
                    const wEl = document.getElementById('waitingList');
                    const pEl = document.getElementById('processedList');
                    
                    if(data.waiting.length === 0) wEl.innerHTML = '<div style="color:#475569;">No files waiting</div>';
                    else wEl.innerHTML = data.waiting.map(f => `
                        <div class="file-item">
                            <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-right:10px;">${f}</span>
                            <button class="btn-del" onclick="deleteFile('${f.replace(/'/g, "\\'")}', 'waiting')">✖</button>
                        </div>
                    `).join('');
                    
                    if(data.processed.length === 0) pEl.innerHTML = '<div style="color:#475569;">No processed files</div>';
                    else pEl.innerHTML = data.processed.map(f => `
                        <div class="file-item">
                            <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-right:10px;">${f}</span>
                            <button class="btn-del" onclick="deleteFile('${f.replace(/'/g, "\\'")}', 'processed')">✖</button>
                        </div>
                    `).join('');
                });
        }

        function deleteFile(filename, type) {
            if (!confirm(`Are you sure you want to delete ${filename}?`)) return;
            
            fetch('/api/delete', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({filename: filename, type: type})
            })
            .then(r => r.json())
            .then(data => {
                if(data.ok) {
                    loadFiles();
                } else {
                    alert("Error deleting file: " + data.message);
                }
            });
        }

        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');
        const uploadStatus = document.getElementById('uploadStatus');

        ['dragover', 'dragenter'].forEach(e => dropZone.addEventListener(e, ev => { ev.preventDefault(); dropZone.classList.add('dragover'); }));
        ['dragleave', 'drop'].forEach(e => dropZone.addEventListener(e, ev => { ev.preventDefault(); dropZone.classList.remove('dragover'); }));

        dropZone.addEventListener('drop', ev => {
            const files = ev.dataTransfer.files;
            if (files.length > 0) handleUpload(files);
        });

        fileInput.addEventListener('change', ev => {
            if (ev.target.files.length > 0) handleUpload(ev.target.files);
        });

        function handleUpload(files) {
            const formData = new FormData();
            for (let i = 0; i < files.length; i++) {
                formData.append('files', files[i]);
            }
            uploadStatus.innerText = "Uploading...";
            fetch('/api/upload', { method: 'POST', body: formData })
                .then(r => r.json())
                .then(data => {
                    uploadStatus.innerText = data.message;
                    loadFiles();
                    setTimeout(() => uploadStatus.innerText = "", 3000);
                });
        }

        // Initial load
        loadFiles();
        fetch('/status').then(r => r.json()).then(data => {
            updateStatusUI(data.status);
            if (data.log.length > 0) document.getElementById('log').innerText = data.log.join('\\n');
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
    app.run(host="0.0.0.0", port=80, threaded=True)