from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    flash,
    jsonify,
    send_file
)
from flask_socketio import SocketIO

import sqlite3
import os
import csv

# Load environment variables manually from .env file if it exists
if os.path.exists(".env"):
    try:
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()
    except Exception as e:
        print(f"Error loading .env file: {e}")
import threading
import hashlib
import datetime
import subprocess
import paramiko

# Platform specific imports for the live interactive terminal shell pipeline
if os.name != 'nt':
    import pty

# ==========================
# IMPORT MODULES
# ==========================

from modules.packet_sniffer import (
    start_capture,
    stop_capture,
    get_packets,
    clear_packets
)

# ==========================
# FLASK & SOCKETIO APP SETUP
# ==========================

app = Flask(__name__)
app.secret_key = "CyberForge_2026_SECRET"

# Initialize the SocketIO real-time communications engine
socketio = SocketIO(app, cors_allowed_origins="*")

# ==========================
# REGISTER BLUEPRINTS & ADDONS
# ==========================
from modules.cyberforge_addons import initialize_addon_database
from modules.scenario_engine import scenario_blueprint
from modules.gamification import gamification_blueprint
from modules.siem_engine import siem_blueprint, set_socketio
from modules.ai_mentor import ai_mentor_blueprint
from modules.report_center import report_center_blueprint

app.register_blueprint(scenario_blueprint)
app.register_blueprint(gamification_blueprint)
app.register_blueprint(siem_blueprint)
app.register_blueprint(ai_mentor_blueprint)
app.register_blueprint(report_center_blueprint)

set_socketio(socketio)

from database import get_db_path

DATABASE = get_db_path()
REPORT_FOLDER = "/tmp/reports" if os.environ.get("VERCEL") else "reports"

if not os.environ.get("VERCEL"):
    os.makedirs("database", exist_ok=True)
os.makedirs(REPORT_FOLDER, exist_ok=True)


# Global variables to manage the running backend shell process pipes
shell_type = 'local'
shell_process = None
fd = None
ssh_client = None
ssh_channel = None

# ==========================
# LIVE INTERACTIVE TERMINAL BACKEND
# ==========================

def kill_shell():
    global shell_process, fd, ssh_client, ssh_channel, shell_type
    shell_type = None
    if ssh_channel:
        try:
            ssh_channel.close()
        except Exception:
            pass
        ssh_channel = None
    if ssh_client:
        try:
            ssh_client.close()
        except Exception:
            pass
        ssh_client = None
    if shell_process:
        try:
            shell_process.terminate()
            shell_process.wait(timeout=1)
        except Exception:
            try:
                shell_process.kill()
            except Exception:
                pass
        shell_process = None
    if fd is not None:
        try:
            os.close(fd)
        except Exception:
            pass
        fd = None

def spawn_shell(selected_type='local', ssh_config=None):
    global shell_process, fd, ssh_client, ssh_channel, shell_type
    kill_shell()
    shell_type = selected_type
    
    if shell_type == 'local':
        if os.name == 'nt':
            env = os.environ.copy()
            env["PROMPT"] = "cyberforge@local-machine:~$ "
            public_dir = os.environ.get("PUBLIC", "C:\\Users\\Public")
            shell_process = subprocess.Popen(
                ['cmd.exe'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=public_dir,
                text=False,
                bufsize=0
            )
            # 🚀 FORCE KICK THE WINDOWS SHELL PROMPT:
            shell_process.stdin.write(b"\n")
            shell_process.stdin.flush()
        else:
            global fd
            pid, fd = pty.fork()
            if pid == 0:
                os.execv('/bin/bash', ['/bin/bash'])
                
    elif shell_type == 'wsl':
        if os.name == 'nt':
            try:
                shell_process = subprocess.Popen(
                    ['wsl.exe', '-d', 'kali-linux', '--cd', '~'],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=False,
                    bufsize=0
                )
                socketio.sleep(0.5)
                if shell_process.poll() is not None:
                    stderr_out = shell_process.stderr.read().decode(errors="ignore") if shell_process.stderr else ""
                    raise Exception(f"WSL process exited. {stderr_out}")
            except Exception as e:
                msg = (
                    "\r\n\033[1;31m[ERROR] Failed to start Kali Linux WSL.\033[0m\r\n"
                    "Please ensure WSL and the Kali Linux distribution are installed on your system.\r\n"
                    "\r\n\033[1;33mHow to install Kali Linux in WSL:\033[0m\r\n"
                    "1. Open PowerShell/CMD as Administrator.\r\n"
                    "2. Run the command: \033[1;36mwsl --install -d kali-linux\033[0m\r\n"
                    "3. Set up your Kali username and password.\r\n"
                    "4. Try connecting again!\r\n\r\n"
                    "Falling back to Windows Local CMD prompt...\r\n\r\n"
                )
                socketio.emit("terminal_output", {"output": msg})
                shell_type = 'local'
                env = os.environ.copy()
                env["PROMPT"] = "cyberforge@kali:~$ "
                public_dir = os.environ.get("PUBLIC", "C:\\Users\\Public")
                shell_process = subprocess.Popen(
                    ['cmd.exe'],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    cwd=public_dir,
                    text=False,
                    bufsize=0
                )
                shell_process.stdin.write(b"\n")
                shell_process.stdin.flush()
        else:
            socketio.emit("terminal_output", {"output": "\r\n[ERROR] WSL option is only available on Windows hosts.\r\n"})
            shell_type = 'local'
            pid, fd = pty.fork()
            if pid == 0:
                os.execv('/bin/bash', ['/bin/bash'])
                
    elif shell_type == 'ssh':
        if not ssh_config:
            socketio.emit("terminal_output", {"output": "\r\n[ERROR] SSH Configuration is missing.\r\n"})
            return
        
        host = ssh_config.get('host', '127.0.0.1')
        port = int(ssh_config.get('port', 22))
        username = ssh_config.get('username', 'kali')
        password = ssh_config.get('password', '')
        
        socketio.emit("terminal_output", {"output": f"\r\nConnecting to SSH server at {host}:{port} as {username}...\r\n"})
        
        try:
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_client.connect(hostname=host, port=port, username=username, password=password, timeout=8)
            ssh_channel = ssh_client.invoke_shell(term='xterm')
            socketio.emit("terminal_output", {"output": "\033[1;32mSSH Connection Established Successfully!\033[0m\r\n\r\n"})
        except Exception as e:
            socketio.emit("terminal_output", {"output": f"\r\n\033[1;31m[ERROR] SSH Connection Failed: {str(e)}\033[0m\r\n"})
            shell_type = 'local'
            spawn_shell('local')

def mask_path(text):
    if not text:
        return text
    try:
        import re
        target_username = "tanvi"
        target_path_win = "c:\\users\\tanvi\\music\\cyberforge"
        target_path_linux = "/mnt/c/users/tanvi/music/cyberforge"
        
        # Replace target path variations
        text = re.sub(re.escape(target_path_win), "C:\\\\Users\\\\victim\\\\Desktop\\\\CyberForge", text, flags=re.IGNORECASE)
        text = re.sub(re.escape(target_path_linux), "/home/victim/Desktop/CyberForge", text, flags=re.IGNORECASE)
        
        cwd = os.getcwd()
        home = os.path.expanduser("~")
        if cwd:
            replacement = ("C:\\Users\\victim\\Desktop\\CyberForge" if os.name == 'nt' else "/home/victim/Desktop/CyberForge").replace('\\', '\\\\')
            text = re.sub(re.escape(cwd), replacement, text, flags=re.IGNORECASE)
        if home:
            replacement = ("C:\\Users\\victim" if os.name == 'nt' else "/home/victim").replace('\\', '\\\\')
            text = re.sub(re.escape(home), replacement, text, flags=re.IGNORECASE)
        
        text = re.sub(re.escape(target_username), "victim", text, flags=re.IGNORECASE)
        username = os.path.basename(home)
        if username:
            text = re.sub(re.escape(username), "victim", text, flags=re.IGNORECASE)
    except Exception:
        pass
    return text

def read_shell_output():
    global shell_process, fd, ssh_channel, shell_type
    while True:
        socketio.sleep(0.02)
        if not shell_type:
            continue
            
        if shell_type == 'ssh':
            if ssh_channel:
                try:
                    if ssh_channel.recv_ready():
                        output = ssh_channel.recv(1024).decode(errors="ignore")
                        if output:
                            socketio.emit("terminal_output", {"output": mask_path(output)})
                except Exception:
                    pass
        elif os.name == 'nt':
            if shell_process:
                try:
                    output = shell_process.stdout.read(1024).decode(errors="ignore")
                    if output:
                        socketio.emit("terminal_output", {"output": mask_path(output)})
                except Exception:
                    pass
        else:
            if fd is not None:
                try:
                    output = os.read(fd, 1024).decode(errors="ignore")
                    if output:
                        socketio.emit("terminal_output", {"output": mask_path(output)})
                except Exception:
                    pass

@socketio.on("terminal_input")
def handle_terminal_input(data):
    global shell_process, fd, ssh_channel, shell_type
    if shell_type == 'ssh' and ssh_channel:
        try:
            ssh_channel.send(data["input"])
        except Exception:
            pass
    elif os.name == 'nt' and shell_process:
        try:
            shell_process.stdin.write(data["input"].encode())
            shell_process.stdin.flush()
        except Exception:
            pass
    elif fd:
        try:
            os.write(fd, data["input"].encode())
        except Exception:
            pass

@socketio.on("select_shell")
def handle_select_shell(data):
    selected_type = data.get("type", "local")
    ssh_config = data.get("ssh", None)
    spawn_shell(selected_type, ssh_config)

# Spin up the background terminal listener stream task thread pool
socketio.start_background_task(target=read_shell_output)

# ==========================
# DATABASE CONNECTION
# ==========================

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# ==========================
# PASSWORD HASH
# ==========================

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ==========================
# ACTIVITY LOGGER
# ==========================

def add_log(username, activity):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO activity_logs (username, activity)
        VALUES (?,?)
    """,(username,activity))
    conn.commit()
    conn.close()

# ==========================
# DATABASE INITIALIZATION
# ==========================

def initialize_database():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        email TEXT UNIQUE,
        password TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS activity_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        activity TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS labs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        description TEXT,
        difficulty TEXT,
        points INTEGER,
        flag TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_labs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        lab_id INTEGER,
        completed INTEGER DEFAULT 0
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reports(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        filename TEXT,
        created DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()

initialize_database()
initialize_addon_database()

VICTIM_STORAGE = os.path.join("database", "victim_storage")

def init_victim_storage(force=False):
    os.makedirs(VICTIM_STORAGE, exist_ok=True)
    
    files = {
        "passwords.txt": (
            "[SECURECORP CRITICAL PASSWORDS]\n"
            "Active Directory Admin: AdminSecure2026!\n"
            "Database Master: DbRootSecurePass%\n"
            "Firewall VPN: VPNGatewayAccess!\n"
        ),
        "financial_records.csv": (
            "TransactionID,Date,Amount,Status\n"
            "TXN10029,2026-07-01,$15000.00,Completed\n"
            "TXN10030,2026-07-02,$450.50,Completed\n"
            "TXN10031,2026-07-05,$1200000.00,Staged\n"
        ),
        "index.html": (
            "<!DOCTYPE html>\n"
            "<html>\n"
            "<head><title>SecureCorp Public Portal</title></head>\n"
            "<body>\n"
            "  <h1>SecureCorp Corporate Node</h1>\n"
            "  <p>System operational. All defensive shields fully functional.</p>\n"
            "</body>\n"
            "</html>\n"
        ),
        "config.json": (
            "{\n"
            "  \"firewall\": \"enabled\",\n"
            "  \"ports_open\": [80, 443, 22],\n"
            "  \"honey_pot\": false\n"
            "}\n"
        )
    }
    
    if force or not os.listdir(VICTIM_STORAGE):
        # Clear existing
        for f in os.listdir(VICTIM_STORAGE):
            try:
                os.remove(os.path.join(VICTIM_STORAGE, f))
            except Exception:
                pass
        # Write default files
        for name, content in files.items():
            with open(os.path.join(VICTIM_STORAGE, name), "w", encoding="utf-8") as f:
                f.write(content)

init_victim_storage()

# ==========================
# LOGIN REQUIRED
# ==========================

def login_required():
    return "username" in session

# ==========================
# THREAT LEVEL
# ==========================

def get_threat_level():
    packet_count = len(get_packets())
    if packet_count < 30:
        return "LOW"
    elif packet_count < 100:
        return "MEDIUM"
    else:
        return "HIGH"

# ==========================
# SECURITY SCORE
# ==========================

def security_score():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM activity_logs")
    logs = cursor.fetchone()[0]
    conn.close()
    return max(0, 100 - logs)

# ==========================================
# ROUTE METHODS & CONTROLLERS
# ==========================================

@app.route("/")
def home():
    if login_required():
        return redirect("/dashboard")
    return render_template("login.html")

@app.route("/login")
def login():
    if login_required():
        return redirect("/dashboard")
    return render_template("login.html")

@app.route("/register")
def register():
    if login_required():
        return redirect("/dashboard")
    return render_template("register.html")

@app.route("/register_user", methods=["POST"])
def register_user():
    username = request.form["username"].strip()
    email = request.form["email"].strip().lower()
    password = request.form["password"]

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE username=?", (username,))
    if cursor.fetchone():
        conn.close()
        flash("Username already exists.")
        return redirect("/register")

    cursor.execute("SELECT * FROM users WHERE email=?", (email,))
    if cursor.fetchone():
        conn.close()
        flash("Email already registered.")
        return redirect("/register")

    encrypted_password = hash_password(password)
    cursor.execute("""
        INSERT INTO users (username, email, password)
        VALUES (?,?,?)
    """,(username, email, encrypted_password))
    conn.commit()
    conn.close()

    add_log(username, "New account created")
    flash("Registration Successful")
    return redirect("/login")

@app.route("/login_user", methods=["POST"])
def login_user():
    email = request.form["email"].strip().lower()
    password = hash_password(request.form["password"])

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password))
    user = cursor.fetchone()
    conn.close()

    if user:
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["email"] = user["email"]
        session["login_time"] = str(datetime.datetime.now())
        add_log(user["username"], "User Logged In")
        return redirect("/dashboard")

    flash("Invalid Email or Password")
    return redirect("/login")

@app.route("/profile")
def profile():
    if not login_required():
        return redirect("/login")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username=?", (session["username"],))
    user = cursor.fetchone()
    conn.close()

    return render_template("profile.html", user=user)

@app.route("/change_password", methods=["POST"])
def change_password():
    if not login_required():
        return redirect("/login")

    current = hash_password(request.form["current"])
    new = hash_password(request.form["new"])

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id=? AND password=?", (session["user_id"], current))
    user = cursor.fetchone()

    if not user:
        conn.close()
        flash("Current password incorrect.")
        return redirect("/profile")

    cursor.execute("UPDATE users SET password=? WHERE id=?", (new, session["user_id"]))
    conn.commit()
    conn.close()

    add_log(session["username"], "Password Changed")
    flash("Password Updated Successfully")
    return redirect("/profile")

@app.route("/logout")
def logout():
    if login_required():
        add_log(session["username"], "User Logged Out")
    session.clear()
    flash("Logged out successfully.")
    return redirect("/login")

@app.route("/dashboard")
def dashboard():
    if not login_required():
        return redirect("/login")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT activity, timestamp FROM activity_logs WHERE username=? ORDER BY id DESC LIMIT 8", (session["username"],))
    logs = cursor.fetchall()

    cursor.execute("SELECT username, activity, timestamp FROM activity_logs ORDER BY id DESC LIMIT 15")
    timeline = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) FROM activity_logs")
    total_logs = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    conn.close()

    add_log(session["username"], "Visited Dashboard")

    return render_template(
        "dashboard.html",
        username=session["username"],
        logs=logs,
        timeline=timeline,
        total_logs=total_logs,
        total_users=total_users,
        packet_count=len(get_packets()),
        threat_level=get_threat_level(),
        security_score=security_score()
    )

@app.route("/activity_logs")
def activity_logs():
    if not login_required():
        return redirect("/login")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM activity_logs ORDER BY id DESC")
    logs = cursor.fetchall()
    conn.close()

    return render_template("activity_logs.html", logs=logs)

@app.route("/attack_timeline")
def attack_timeline():
    if not login_required():
        return redirect("/login")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM activity_logs ORDER BY timestamp DESC")
    attacks = cursor.fetchall()
    conn.close()

    return render_template("attack_timeline.html", attacks=attacks)

@app.route("/api/dashboard_stats")
def dashboard_stats():
    if not login_required():
        return jsonify({})

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM activity_logs")
    total_logs = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    conn.close()

    return jsonify({
        "security_score": security_score(),
        "threat_level": get_threat_level(),
        "packets": len(get_packets()),
        "logs": total_logs,
        "users": total_users
    })

@app.route("/api/recent_logs")
def recent_logs():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT username, activity, timestamp FROM activity_logs ORDER BY id DESC LIMIT 10")
    logs = cursor.fetchall()
    conn.close()

    data = [{"username": row["username"], "activity": row["activity"], "timestamp": row["timestamp"]} for row in logs]
    return jsonify(data)

@app.route("/api/timeline")
def api_timeline():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT username, activity, timestamp FROM activity_logs ORDER BY id DESC LIMIT 20")
    timeline = cursor.fetchall()
    conn.close()

    result = [{"username": row["username"], "activity": row["activity"], "timestamp": row["timestamp"]} for row in timeline]
    return jsonify(result)

# ==========================================
# GLOBAL LAB STATE SYNCHRONIZATION POOL
# ==========================================
current_lab_attack_state = {
    "active_incident": "none",
    "data_exfiltrated": False,
    "malware_installed": False,
    "defaced": False,
    "phishing_kit": False,
    "ransomware_active": False,
    "privilege_escalated": False,
    "beaconing": "No",
    "integrity_status": "Clean",
    "threat_logs": []
}

@app.route("/hacker")
def hacker():
    if not login_required():
        return redirect("/login")

    # Initialize the backend terminal process session wrapper pipeline
    spawn_shell()
    
    add_log(session["username"], "Opened Live Hacker Terminal Interface")
    return render_template("hacker.html", username=session["username"])

@app.route("/victim")
def victim():
    if not login_required():
        return redirect("/login")

    add_log(session["username"], "Opened Victim Interface")
    return render_template("victim.html", username=session["username"])

@app.route("/api/simulation/status", methods=["GET"])
def get_simulation_status():
    if not login_required():
        return jsonify({"active_incident": "none"})
    return jsonify(current_lab_attack_state)

@app.route("/api/simulation/trigger", methods=["POST"])
def update_simulation_status():
    if not login_required():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    data = request.get_json() or {}
    attack_type = data.get("attack_type", "none")
    current_lab_attack_state["active_incident"] = attack_type
    
    add_log(session["username"], f"Triggered Lab Simulation Event Loop: {attack_type}")
    return jsonify({"status": "success", "current_state": current_lab_attack_state["active_incident"]})

@app.route("/api/lab/files", methods=["GET"])
def get_lab_files():
    if not login_required():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    try:
        files = os.listdir(VICTIM_STORAGE)
        return jsonify({"status": "success", "files": files})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/lab/execute_exploit", methods=["POST"])
def execute_lab_exploit():
    if not login_required():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
        
    data = request.get_json() or {}
    vector = data.get("vector")
    filename = data.get("filename")
    
    global current_lab_attack_state
    
    if vector == "exfiltration":
        current_lab_attack_state["data_exfiltrated"] = True
        current_lab_attack_state["active_incident"] = "exfiltration"
        current_lab_attack_state["beaconing"] = "Yes"
        log_msg = "ALERT: Outbound transfer anomaly - 50,000 credit records staged"
        if log_msg not in current_lab_attack_state["threat_logs"]:
            current_lab_attack_state["threat_logs"].append(log_msg)
        add_log(session["username"], "Simulated Data Exfiltration exploit: Staged mock records for download")
        
    elif vector == "malware":
        current_lab_attack_state["malware_installed"] = True
        current_lab_attack_state["active_incident"] = "malware"
        backdoor_path = os.path.join(VICTIM_STORAGE, "backdoor_svc.exe")
        with open(backdoor_path, "w", encoding="utf-8") as f:
            f.write("[MOCK MALWARE PROCESS svc]\nHost IP: 192.168.24.131\nStatus: Persistent\n")
        log_msg = "ALERT: Rogue process 'backdoor_svc.exe' discovered running in background"
        if log_msg not in current_lab_attack_state["threat_logs"]:
            current_lab_attack_state["threat_logs"].append(log_msg)
        add_log(session["username"], "Simulated Malware & Backdoor Installation exploit: Placed backdoor_svc.exe")
        
    elif vector == "defacement":
        current_lab_attack_state["defaced"] = True
        current_lab_attack_state["active_incident"] = "defacement"
        current_lab_attack_state["integrity_status"] = "Defaced"
        defaced_html = (
            "<!DOCTYPE html>\n<html>\n"
            "<head><title>HACKED BY CYBERFORGE</title></head>\n"
            "<body style=\"background: black; color: #ff3366; text-align: center; font-family: monospace; padding-top: 100px;\">\n"
            "  <h1>🚫 HACKED BY CYBERFORGE 🚫</h1>\n"
            "  <p>YOUR WEB PORTAL SECURITY HAS BEEN BREACHED.</p>\n"
            "</body>\n</html>\n"
        )
        index_path = os.path.join(VICTIM_STORAGE, "index.html")
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(defaced_html)
        log_msg = "CRITICAL: Web Portal Integrity violation - index.html modified by external IP"
        if log_msg not in current_lab_attack_state["threat_logs"]:
            current_lab_attack_state["threat_logs"].append(log_msg)
        add_log(session["username"], "Simulated SEO Spam & Defacement exploit: Modified index.html")
        
    elif vector == "phishing":
        current_lab_attack_state["phishing_kit"] = True
        current_lab_attack_state["active_incident"] = "phishing"
        phish_html = (
            "<form action=\"/phish-catch\">\n"
            "  <h2>SecureCorp SSO Authentication</h2>\n"
            "  <input type=\"text\" name=\"user\" placeholder=\"Username\">\n"
            "  <input type=\"password\" name=\"pass\" placeholder=\"Password\">\n"
            "  <input type=\"submit\" value=\"Sign In\">\n"
            "</form>\n"
        )
        phish_path = os.path.join(VICTIM_STORAGE, "secure_login.html")
        with open(phish_path, "w", encoding="utf-8") as f:
            f.write(phish_html)
        log_msg = "ALERT: Unexpected phishing form 'secure_login.html' detected in public folder"
        if log_msg not in current_lab_attack_state["threat_logs"]:
            current_lab_attack_state["threat_logs"].append(log_msg)
        add_log(session["username"], "Simulated Phishing exploit: Hosted fake login page")
        
    elif vector == "ransomware":
        current_lab_attack_state["ransomware_active"] = True
        current_lab_attack_state["active_incident"] = "ransomware"
        current_lab_attack_state["integrity_status"] = "Compromised"
        for f in os.listdir(VICTIM_STORAGE):
            if not f.endswith(".locked"):
                src = os.path.join(VICTIM_STORAGE, f)
                dst = src + ".locked"
                try:
                    os.rename(src, dst)
                except Exception:
                    pass
        log_msg = "CRITICAL: Ransomware outbreak detected. Symmetric cryptolock routine active"
        if log_msg not in current_lab_attack_state["threat_logs"]:
            current_lab_attack_state["threat_logs"].append(log_msg)
        add_log(session["username"], "Simulated Ransomware Cryptolock: Encrypted target files with .locked extension")
        
    elif vector == "privilege_escalation":
        current_lab_attack_state["privilege_escalated"] = True
        current_lab_attack_state["active_incident"] = "privilege_escalation"
        log_msg = "WARNING: Local service account token elevated to NT AUTHORITY\\SYSTEM"
        if log_msg not in current_lab_attack_state["threat_logs"]:
            current_lab_attack_state["threat_logs"].append(log_msg)
        add_log(session["username"], "Simulated Local Privilege Escalation: Elevated active session token to SYSTEM")
        
    elif vector == "rm":
        if not filename:
            return jsonify({"status": "error", "message": "Filename not specified"}), 400
        file_path = os.path.join(VICTIM_STORAGE, filename)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                log_msg = f"ALERT: File '{filename}' deleted from storage registry"
                if log_msg not in current_lab_attack_state["threat_logs"]:
                    current_lab_attack_state["threat_logs"].append(log_msg)
                add_log(session["username"], f"Simulated Terminal Deletion: Deleted file '{filename}'")
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 500
        else:
            return jsonify({"status": "error", "message": "File not found"}), 404
            
    # Remediation cases
    elif vector == "remediate_exfil":
        current_lab_attack_state["data_exfiltrated"] = False
        current_lab_attack_state["beaconing"] = "No"
        current_lab_attack_state["threat_logs"] = [l for l in current_lab_attack_state["threat_logs"] if "exfiltrated" not in l and "exfiltration" not in l and "outbound" not in l]
        add_log(session["username"], "Defensive Remediation: Data exfiltration outbound flow blocked")
        
    elif vector == "remediate_malware":
        current_lab_attack_state["malware_installed"] = False
        backdoor_path = os.path.join(VICTIM_STORAGE, "backdoor_svc.exe")
        if os.path.exists(backdoor_path):
            try:
                os.remove(backdoor_path)
            except Exception:
                pass
        current_lab_attack_state["threat_logs"] = [l for l in current_lab_attack_state["threat_logs"] if "backdoor" not in l]
        add_log(session["username"], "Defensive Remediation: Quarantined and deleted 'backdoor_svc.exe'")
        
    elif vector == "remediate_defacement":
        current_lab_attack_state["defaced"] = False
        if not current_lab_attack_state["ransomware_active"]:
            current_lab_attack_state["integrity_status"] = "Clean"
        default_index = (
            "<!DOCTYPE html>\n<html>\n"
            "<head><title>SecureCorp Public Portal</title></head>\n"
            "<body>\n"
            "  <h1>SecureCorp Corporate Node</h1>\n"
            "  <p>System operational. All defensive shields fully functional.</p>\n"
            "</body>\n"
            "</html>\n"
        )
        suffix = ".locked" if current_lab_attack_state["ransomware_active"] else ""
        index_path = os.path.join(VICTIM_STORAGE, "index.html" + suffix)
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(default_index)
        current_lab_attack_state["threat_logs"] = [l for l in current_lab_attack_state["threat_logs"] if "Defacement" not in l and "index.html" not in l]
        add_log(session["username"], "Defensive Remediation: Restored web portal index.html integrity")
        
    elif vector == "remediate_phishing":
        current_lab_attack_state["phishing_kit"] = False
        phish_path = os.path.join(VICTIM_STORAGE, "secure_login.html")
        if os.path.exists(phish_path):
            try:
                os.remove(phish_path)
            except Exception:
                pass
        phish_path_locked = os.path.join(VICTIM_STORAGE, "secure_login.html.locked")
        if os.path.exists(phish_path_locked):
            try:
                os.remove(phish_path_locked)
            except Exception:
                pass
        current_lab_attack_state["threat_logs"] = [l for l in current_lab_attack_state["threat_logs"] if "phishing" not in l and "secure_login.html" not in l]
        add_log(session["username"], "Defensive Remediation: Torndown phishing kit 'secure_login.html'")
        
    elif vector == "remediate_ransomware":
        current_lab_attack_state["ransomware_active"] = False
        if not current_lab_attack_state["defaced"]:
            current_lab_attack_state["integrity_status"] = "Clean"
        else:
            current_lab_attack_state["integrity_status"] = "Defaced"
        for f in os.listdir(VICTIM_STORAGE):
            if f.endswith(".locked"):
                src = os.path.join(VICTIM_STORAGE, f)
                dst = src[:-7] # strip .locked
                try:
                    os.rename(src, dst)
                except Exception:
                    pass
        current_lab_attack_state["threat_logs"] = [l for l in current_lab_attack_state["threat_logs"] if "Ransomware" not in l and "cryptolock" not in l]
        add_log(session["username"], "Defensive Remediation: Restored target storage files from backup snapshot")
        
    elif vector == "remediate_privesc":
        current_lab_attack_state["privilege_escalated"] = False
        current_lab_attack_state["threat_logs"] = [l for l in current_lab_attack_state["threat_logs"] if "privilege" not in l and "authority" not in l and "NT AUTHORITY" not in l]
        add_log(session["username"], "Defensive Remediation: Revoked elevated administrative session tokens")
        
    elif vector == "reset":
        init_victim_storage(force=True)
        current_lab_attack_state["active_incident"] = "none"
        current_lab_attack_state["data_exfiltrated"] = False
        current_lab_attack_state["malware_installed"] = False
        current_lab_attack_state["defaced"] = False
        current_lab_attack_state["phishing_kit"] = False
        current_lab_attack_state["ransomware_active"] = False
        current_lab_attack_state["privilege_escalated"] = False
        current_lab_attack_state["beaconing"] = "No"
        current_lab_attack_state["integrity_status"] = "Clean"
        current_lab_attack_state["threat_logs"] = []
        add_log(session["username"], "Reset simulation lab state")
        
    # Recalculate active incident if any
    active = "none"
    if current_lab_attack_state["ransomware_active"]:
        active = "ransomware"
    elif current_lab_attack_state["defaced"]:
        active = "defacement"
    elif current_lab_attack_state["malware_installed"]:
        active = "malware"
    elif current_lab_attack_state["phishing_kit"]:
        active = "phishing"
    elif current_lab_attack_state["data_exfiltrated"]:
        active = "exfiltration"
    elif current_lab_attack_state["privilege_escalated"]:
        active = "privilege_escalation"
    current_lab_attack_state["active_incident"] = active
    
    return jsonify({"status": "success", "state": current_lab_attack_state})

@app.route("/packet_sniffer")
def packet_sniffer():
    if not login_required():
        return redirect("/login")

    add_log(session["username"], "Opened Packet Sniffer")
    return render_template("packet_sniffer.html", username=session["username"])

@app.route("/password_analyzer")
def password_analyzer():
    if not login_required():
        return redirect("/login")
        
    add_log(session["username"], "Opened Password Analyzer")
    return render_template("password_analyzer.html", username=session["username"])

def get_local_knowledge_reply(question):
    """Checks the local knowledge base file for any matching keywords."""
    import json
    q = question.lower()
    kb_path = "database/knowledge_base.json"
    
    if os.path.exists(kb_path):
        try:
            with open(kb_path, "r", encoding="utf-8") as f:
                kb = json.load(f)
            # Find matching keyword
            for keyword, answer in kb.items():
                if keyword in q:
                    return answer
        except Exception as e:
            print(f"Error loading knowledge base: {e}")
            
    return None

def query_local_ollama(question):
    """Sends query to local Ollama chat API service if online on port 11434."""
    import requests
    url = "http://localhost:11434/api/chat"
    
    # Load model configuration from environment (defaults to llama3)
    model_name = os.environ.get("OLLAMA_MODEL") or "llama3"
    
    system_prompt = (
        "You are CyberForge AI, an advanced elite Cybersecurity Operations Center (SOC) Copilot. "
        "Your strictly enforced operational parameters require you to ONLY answer questions directly "
        "related to cybersecurity, networking, ethical hacking, digital forensics, defensive parameters, "
        "and malware analysis. If the user asks anything completely unrelated to cybersecurity, you must "
        "politely decline."
    )
    
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question}
        ],
        "stream": False
    }
    
    try:
        # Check connection with a quick 5-second timeout to avoid locking the UI thread
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code == 200:
            result = response.json()
            answer = result.get("message", {}).get("content", "")
            return answer
    except Exception as e:
        print(f"Ollama Connection/Execution Error: {e}")
        
    return None

def query_groq_api(question):
    """Sends query to Groq Cloud API service if GROQ_API_KEY is configured in .env."""
    import requests
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
        
    url = "https://api.groq.com/openai/v1/chat/completions"
    model_name = os.environ.get("GROQ_MODEL") or "llama-3.3-70b-versatile"
    
    system_prompt = (
        "You are CyberForge AI, an advanced elite Cybersecurity Operations Center (SOC) Copilot. "
        "Your strictly enforced operational parameters require you to ONLY answer questions directly "
        "related to cybersecurity, networking, ethical hacking, digital forensics, defensive parameters, "
        "and malware analysis. If the user asks anything completely unrelated to cybersecurity, you must "
        "politely decline."
    )
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question}
        ],
        "temperature": 0.5,
        "max_tokens": 1024,
        "stream": False
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=8)
        if response.status_code == 200:
            result = response.json()
            answer = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            return answer
        else:
            print(f"Groq API Error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Groq Request Error: {e}")
        
    return None

def get_mock_copilot_reply(question):
    import json
    kb_path = "database/knowledge_base.json"
    keywords = ["nmap", "sql injection", "xss", "ransomware", "phishing", "firewall", "malware", "wireshark", "ssh"]
    
    if os.path.exists(kb_path):
        try:
            with open(kb_path, "r", encoding="utf-8") as f:
                kb = json.load(f)
                keywords = list(kb.keys())
        except Exception:
            pass
            
    keywords_list = ", ".join(f"**{kw}**" for kw in keywords)
    
    api_guide = (
        "\n\n---"
        "\n💡 **How to activate Live Gemini AI Mode for free:**"
        "\n1. Go to **[Google AI Studio](https://aistudio.google.com/)**."
        "\n2. Generate a free API Key."
        "\n3. Open the `.env` file in the project folder."
        "\n4. Set `GEMINI_API_KEY=your_new_key_here`."
        "\n5. Restart the server. The Cyber Copilot will connect automatically!"
    )
    
    # Simple greeting offline fallback
    q = question.lower()
    if "hello" in q or "hi" in q or "hey" in q:
        return (
            "🤖 **CyberForge SOC Copilot [OFFLINE MODE]**\n\n"
            "System initialized. Connection status: *Local Loopback (Offline)*.\n"
            "I am ready to assist you with local cybersecurity queries, or you can supply an API key to enable live intelligence."
            + api_guide
        )
    
    return (
        "🛡️ **CyberForge SOC Copilot [OFFLINE MODE]**\n\n"
        "I didn't find an offline match for your question, and my live Gemini link is currently offline.\n\n"
        f"👉 **Available Offline Topics**: You can ask me about: {keywords_list}.\n"
        "Try asking: *\"What is SQL Injection?\"* or *\"Nmap scan commands\"*."
        + api_guide
    )

# ==========================================
# REAL LIVE GEMINI AI CYBER COPILOT
# ==========================================
@app.route("/api/ai", methods=["POST"])
def live_gemini_copilot_api():
    if not login_required():
        return jsonify({"reply": "Login Required."})

    question = request.json.get("question", "")
    
    # 1. Attempt to resolve query from local knowledge base (instant, cached answers)
    local_answer = get_local_knowledge_reply(question)
    if local_answer:
        add_log(session["username"], f"Used Local Knowledge Base for query: {question[:30]}...")
        return jsonify({"reply": local_answer})

    # 2. Attempt to resolve query from Groq Cloud API (high-limit free cloud LLM)
    groq_answer = query_groq_api(question)
    if groq_answer:
        add_log(session["username"], f"Used Groq Cloud API for query: {question[:30]}...")
        return jsonify({"reply": groq_answer})

    # 3. Attempt to resolve query from Local Ollama service (if running offline)
    ollama_answer = query_local_ollama(question)
    if ollama_answer:
        add_log(session["username"], f"Used Local Ollama LLM for query: {question[:30]}...")
        return jsonify({"reply": f"🤖 **copilot (local-llm):**\n\n{ollama_answer}"})

    # 4. Otherwise, fall back to Gemini API
    api_key = os.environ.get("GEMINI_API_KEY")
    
    # Check if API key is missing or default placeholder
    is_key_placeholder = not api_key or api_key == "AQ.Ab8RN6KagyNAoKb74gEsjV5R3m9N1yRLPAwz_g2UhHNC8APhFw"
    
    if is_key_placeholder:
        answer = get_mock_copilot_reply(question)
    else:
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            
            system_prompt = (
                "You are CyberForge AI, an advanced elite Cybersecurity Operations Center (SOC) Copilot. "
                "Your strictly enforced operational parameters require you to ONLY answer questions directly "
                "related to cybersecurity, networking, ethical hacking, digital forensics, defensive parameters, "
                "and malware analysis. If the user asks anything completely unrelated to cybersecurity, you must "
                "politely decline."
            )

            model = genai.GenerativeModel(model_name='gemini-3.5-flash', system_instruction=system_prompt)
            response = model.generate_content(question)
            answer = response.text
        except Exception as e:
            print(f"Gemini API Connection Error: {e}")
            answer = f"[OFFLINE MODE - API Error: {str(e)}]\n\n" + get_mock_copilot_reply(question)

    add_log(session["username"], "Used Live Gemini AI Cyber Copilot")
    return jsonify({"reply": answer})

@app.route("/ai_copilot")
def ai_copilot():
    if not login_required():
        return redirect("/login")
    return render_template("ai_copilot.html", username=session["username"])

@app.route("/ai_pentester")
def ai_pentester():
    if not login_required():
        return redirect("/login")
    return render_template("ai_pentester.html", username=session["username"])

@app.route("/api/ai_agent/step", methods=["POST"])
def ai_agent_step():
    if not login_required():
        return jsonify({"status": "error", "message": "Login Required."}), 401
    
    data = request.get_json() or {}
    lesson_key = data.get("lesson_key", "sql_injection")
    history = data.get("history", [])
    
    # Target configurations
    targets_config = {
        "sql_injection": {
            "title": "SQL Injection UNION Exploitation",
            "desc": "Simulated target database portal backend. Find a SQL injection exploit to dump the users table flag.",
            "flag": "SQLI_UNION_SUCCESS_99",
            "hint": "Try using UNION SELECT query blocks to merge system tables with columns count."
        },
        "lfi": {
            "title": "LFI File Directory Traversal",
            "desc": "Simulated address view page (?page=home.php). Discover the path to passwd logs and extract the admin hash.",
            "flag": "$6$fakebank$9x12yz",
            "hint": "Use directory traversal characters (../../../../) to target /etc/passwd."
        },
        "privilege_escalation": {
            "title": "Linux SUID Privilege Escalation",
            "desc": "Low privilege shell environment on victim host. Enumerate SUID binaries and elevate shell privileges.",
            "flag": "ROOT_PRIV_ESC_LOCAL_99",
            "hint": "Search for SUID permissions using find, look for /usr/bin/find, and execute escape command find -exec."
        },
        "password_attacks": {
            "title": "SSH Service Dict Password Brute Force",
            "desc": "SSH endpoint running on internal IP 10.0.0.15. Crack credentials using Hydra brute force.",
            "flag": "shadow123",
            "hint": "Run brute force commands using hydra on target machine 10.0.0.15 SSH server."
        },
        "packet_sniffing": {
            "title": "Cleartext HTTP Token Capture Sniffer",
            "desc": "Interface eth0 running unencrypted protocol traffic. Monitor network frames to capture login token.",
            "flag": "FORGE99X",
            "hint": "Activate raw sniffer Promiscuous inspection logs to reassemble plaintext packets."
        }
    }
    
    cfg = targets_config.get(lesson_key, targets_config["sql_injection"])
    
    # Format command history for LLM prompt context
    history_str = ""
    for entry in history:
        history_str += f"Command: {entry.get('command')}\nOutput: {entry.get('output')}\n"
    if not history_str:
        history_str = "(No commands executed yet. Start by checking your context.)\n"
        
    system_prompt = (
        "You are an autonomous AI red-team pentesting agent. Your mission is to identify vulnerabilities, "
        f"probe them, and retrieve flag keys from the target environment: {cfg['title']}\n"
        f"Target description: {cfg['desc']}\n"
        f"Hints/Vulnerabilities info: {cfg['hint']}\n"
        f"Target secret key flag to discover: {cfg['flag']}\n\n"
        "You have access to a local shell. Here is your execution history:\n"
        f"{history_str}\n"
        "Choose the next command to execute on the host. Be direct, logical, and technical. "
        "IMPORTANT: You MUST respond ONLY in valid JSON format matching this schema. Do not output markdown, preambles, or backticks:\n"
        "{\n"
        '  "thought": "Your tactical analysis / thinking string",\n'
        '  "command": "The next shell command to execute"\n'
        "}"
    )
    
    try:
        import google.generativeai as genai
        import json
        api_key = os.environ.get("GEMINI_API_KEY")
        
        # Check if API key is missing or default placeholder
        is_key_placeholder = not api_key or api_key == "AQ.Ab8RN6KagyNAoKb74gEsjV5R3m9N1yRLPAwz_g2UhHNC8APhFw"
        if is_key_placeholder:
            raise ValueError("Using default/placeholder API key. Triggering fallback.")
            
        genai.configure(api_key=api_key)
        
        model = genai.GenerativeModel(model_name='gemini-3.5-flash')
        response = model.generate_content(system_prompt)
        
        res_text = response.text.strip()
        if res_text.startswith("```json"):
            res_text = res_text[7:]
        if res_text.endswith("```"):
            res_text = res_text[:-3]
        res_text = res_text.strip()
        
        parsed = json.loads(res_text)
        thought = parsed.get("thought", "Analyzing system structure...")
        command = parsed.get("command", "ls -la").strip()
    except Exception as e:
        print(f"Gemini API AI Agent error: {e}")
        # Intelligent fallback behavior to ensure simulation works without network glitches
        thought = "Probing system configuration directory indexes..."
        if lesson_key == "sql_injection":
            command = "' UNION SELECT username, password_hash, sys_secret_flag FROM users --"
        elif lesson_key == "lfi":
            command = "../../../../etc/passwd"
        elif lesson_key == "privilege_escalation":
            command = "find / -perm -4000 -type f 2>/dev/null"
        elif lesson_key == "password_attacks":
            command = "hydra -l admin -P wordlist.txt ssh://10.0.0.15"
        else:
            command = "tcpdump -A -i eth0"

    # Command Execution Simulation
    cmd_clean = command.lower()
    output = ""
    status = "ACTIVE"
    
    if lesson_key == "sql_injection":
        if "union" in cmd_clean and "users" in cmd_clean:
            output = (
                "+-------------------+---------------------+----------------------------+\n"
                "| username          | password_hash       | sys_secret_flag            |\n"
                "+-------------------+---------------------+----------------------------+\n"
                "| admin             | $2b$12$ExPloit...   | SQLI_UNION_SUCCESS_99      |\n"
                "| t-staff-fakebank  | $2b$12$FkBnK89...   | SQLI_MEMBER_TOKEN_4452     |\n"
                "+-------------------+---------------------+----------------------------+"
            )
        elif "1=1" in cmd_clean or "or '" in cmd_clean:
            output = "[SUCCESS] Authentication Bypass: Welcome Admin!"
        else:
            output = "[SYSTEM] Database error: unrecognized column or syntax near query."
            
    elif lesson_key == "lfi":
        if "passwd" in cmd_clean or "etc" in cmd_clean or "../" in cmd_clean:
            output = (
                "root:x:0:0:root:/root:/bin/bash\n"
                "bin:x:1:1:bin:/bin:/sbin/nologin\n"
                "operator:x:11:0:operator:/root:/sbin/nologin\n"
                "administrator:x:0:0::/root:/bin/bash:$6$fakebank$9x12yz"
            )
        else:
            output = "[INFO] Rendering static file layout template. Error: parameter path did not target a file."
            
    elif lesson_key == "privilege_escalation":
        if "find" in cmd_clean and ("-perm" in cmd_clean or "-4000" in cmd_clean):
            output = (
                "/usr/lib/dbus-1.0/dbus-daemon-launch-helper\n"
                "/usr/bin/passwd\n"
                "/usr/bin/find (SUID Bit Enabled!)"
            )
        elif "find" in cmd_clean and "-exec" in cmd_clean and "sh" in cmd_clean:
            output = (
                "[SUCCESS] SUID find escape dropped low-priv shell to root!\n"
                "root@victim-machine:~# id\n"
                "uid=1001(user) gid=1001(user) euid=0(root) egid=0(root)\n"
                "root@victim-machine:~# cat /root/root.txt\n"
                "FLAG VALUE: ROOT_PRIV_ESC_LOCAL_99"
            )
        elif "id" in cmd_clean:
            output = "uid=1001(user) gid=1001(user) groups=1001(user)"
        else:
            output = "[SYSTEM] Command executed in low-privilege context. Target binary escape sequence not matched."
            
    elif lesson_key == "password_attacks":
        if "hydra" in cmd_clean or "ssh" in cmd_clean:
            output = (
                "[ATTEMPT] user: admin | password: password123 -> Access Denied\n"
                "[ATTEMPT] user: admin | password: shadow123 -> [SUCCESS] MATCH FOUND!\n"
                "[10.0.0.15] Host cracked - 1 valid credential found:\n"
                "Target user account: admin | Valid password: shadow123"
            )
        else:
            output = "Ready to launch password dictionary attack framework array. Use hydra to target SSH service."
            
    elif lesson_key == "packet_sniffing":
        if "tcpdump" in cmd_clean or "sniff" in cmd_clean or "intercept" in cmd_clean or "eth0" in cmd_clean:
            output = (
                "[IP] 192.168.1.22 -> 10.0.0.5 | HTTP POST Request (Plaintext)\n"
                "<b>[UNENCRYPTED PAYLOAD REASSEMBLED]:</b>\n"
                "POST /api/login HTTP/1.1\n"
                "Host: internal.bank.corp\n"
                "Content-Type: application/json\n\n"
                '{ "user": "admin", "session_access_token": "FORGE99X" }'
            )
        else:
            output = "No live network interface streams hook found. Try promiscuous sniffer capture commands."
            
    else:
        output = "[SYSTEM] command executed successfully, exit code 0"

    # Evaluate if target secret key flag was leaked/extracted
    if cfg["flag"].lower() in output.lower():
        status = "ROOTED"
        # Register completion in user database automatically!
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT id, xp_value, title FROM academy_lessons WHERE lesson_key=?", (lesson_key,))
            lesson_row = cursor.fetchone()
            if lesson_row:
                lesson_id = lesson_row["id"]
                # Insert into lab_progress
                cursor.execute("SELECT * FROM lab_progress WHERE username=? AND lab_id=?", (session["username"], lesson_id))
                progress = cursor.fetchone()
                if not progress:
                    cursor.execute(
                        "INSERT INTO lab_progress (username, lab_id, completed, flag) VALUES (?, ?, 1, ?)",
                        (session["username"], lesson_id, cfg["flag"])
                    )
                    conn.commit()
                    try:
                        from modules.gamification import award_xp
                        award_xp(session["username"], lesson_row["xp_value"], lesson_row["xp_value"], f"Completed Academy Lab via AI Pentester: {lesson_row['title']}")
                    except Exception as e:
                        print(f"Error awarding gamification XP on AI pentester: {e}")
            conn.close()
            add_log(session["username"], f"Completed Academy Lab via AI Agent: {cfg['title']}")
        except Exception as e:
            print(f"Failed to record AI agent progress: {e}")

    return jsonify({
        "thought": thought,
        "command": command,
        "output": output,
        "status": status,
        "flag": cfg["flag"] if status == "ROOTED" else None
    })

@app.route("/labs/defensive")
def defensive_lab():
    if not login_required():
        return redirect("/login")
    return render_template("defensive_lab.html", username=session.get("username", "Operator"))

@app.route("/academy")
def academy():
    if not login_required():
        return redirect("/login")

    add_log(session["username"], "Opened Cyber Defense Academy")
    lessons = [
        {"title":"Social Engineering", "difficulty":"Easy"},
        {"title":"Password Attacks", "difficulty":"Easy"},
        {"title":"Packet Sniffing", "difficulty":"Medium"},
        {"title":"SQL Injection", "difficulty":"Medium"},
        {"title":"XSS", "difficulty":"Medium"},
        {"title":"Local File Inclusion (LFI)", "difficulty":"Hard"},
        {"title":"Privilege Escalation", "difficulty":"Hard"},
        {"title":"Windows Enumeration", "difficulty":"Medium"},
        {"title":"Linux Enumeration", "difficulty":"Medium"}
    ]
    return render_template("academy.html", username=session["username"], lessons=lessons)

@app.route("/api/academy/verify", methods=["POST"])
def verify_academy_flag():
    if not login_required():
        return jsonify({"status": "error", "message": "Login Required."}), 401
    
    data = request.get_json() or {}
    lesson_key = data.get("lesson_key")
    submitted_answer = data.get("answer", "").strip()
    
    if not lesson_key or not submitted_answer:
        return jsonify({"status": "error", "message": "Lesson key and answer are required."}), 400
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, correct_flag, title, xp_value FROM academy_lessons WHERE lesson_key=?", (lesson_key,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return jsonify({"status": "error", "message": "Invalid lesson selection."}), 400
        
    lesson_id = row["id"]
    correct_flag = row["correct_flag"]
    
    is_correct = False
    if submitted_answer.lower() == correct_flag.lower():
        is_correct = True
    else:
        # Check raw input passwords/hashes mapping
        raw_answers_map = {
            'social_engineering': 'secure-update-fakebank.com',
            'password_attacks': 'shadow123',
            'packet_sniffing': 'FORGE99X',
            'sql_injection': 'SQLI_UNION_SUCCESS_99',
            'xss': 'XSS_COOKIE_STEAL_887',
            'lfi': '$6$fakebank$9x12yz',
            'privilege_escalation': 'ROOT_PRIV_ESC_LOCAL_99',
            'windows_enumeration': 'WIN_SYS_ENUM_776',
            'linux_enumeration': 'lx_dev_portal_alpha'
        }
        mapped_ans = raw_answers_map.get(lesson_key, "")
        if mapped_ans and submitted_answer.lower() == mapped_ans.lower():
            is_correct = True
            
    if is_correct:
        cursor.execute("SELECT * FROM lab_progress WHERE username=? AND lab_id=?", (session["username"], lesson_id))
        progress = cursor.fetchone()
        
        if not progress:
            cursor.execute(
                "INSERT INTO lab_progress (username, lab_id, completed, flag) VALUES (?, ?, 1, ?)",
                (session["username"], lesson_id, correct_flag)
            )
            conn.commit()
            try:
                from modules.gamification import award_xp
                award_xp(session["username"], row["xp_value"], row["xp_value"], f"Completed Academy Lab: {row['title']}")
            except Exception as e:
                print(f"Error awarding gamification XP on lab completion: {e}")
            
        conn.close()
        add_log(session["username"], f"Completed Academy Lab: {row['title']}")
        return jsonify({"status": "success", "flag": correct_flag})
    else:
        conn.close()
        return jsonify({"status": "failed", "message": "Incorrect answer entry parameter field check. Re-examine details closely!"})

@app.route("/report")
def report():
    if not login_required():
        return redirect("/login")

    add_log(session["username"], "Opened Report Generator")
    return render_template("report.html", username=session["username"])

# ==========================================
# START / STOP PACKET CAPTURE ENGINE
# ==========================================

capture_thread = None
capture_running = False

@app.route("/api/start_capture", methods=["POST"])
def api_start_capture_trigger():
    global capture_thread, capture_running

    if not login_required():
        return jsonify({"status": "error", "message": "Login Required"})

    if capture_running:
        return jsonify({"status": "running", "message": "Capture already running"})

    capture_running = True
    capture_thread = threading.Thread(target=start_capture, daemon=True)
    capture_thread.start()

    add_log(session["username"], "Started Packet Capture")
    return jsonify({"status": "success", "message": "Packet Capture Started"})

@app.route("/api/stop_capture", methods=["POST"])
def api_stop_capture_trigger():
    global capture_running
    if not login_required():
        return jsonify({"status": "error"})

    stop_capture()
    capture_running = False
    add_log(session["username"], "Stopped Packet Capture")
    return jsonify({"status": "success"})

@app.route("/api/live_packets")
def api_live_packets_fetch():
    if not login_required():
        return jsonify([])

    packets = get_packets()
    requested_proto = request.args.get("protocol", "ALL").upper()
    search_keyword = request.args.get("search", "").lower()

    filtered_list = packets
    if requested_proto != "ALL":
        filtered_list = [p for p in filtered_list if p["protocol"] == requested_proto]

    if search_keyword:
        filtered_list = [
            p for p in filtered_list if
            search_keyword in p["src"].lower() or
            search_keyword in p["dst"].lower() or
            search_keyword in p["info"].lower()
        ]
    return jsonify(filtered_list)

@app.route("/api/export_capture")
def api_export_capture_redirect():
    return redirect("/export_packets")

@app.route("/api/sniffer/clear", methods=["POST"])
def api_clear_packets():
    if not login_required():
        return jsonify({"status":"error"})

    clear_packets()
    add_log(session["username"], "Cleared Packet Capture")
    return jsonify({"status":"success"})

@app.route("/api/sniffer/stats")
def api_sniffer_stats():
    packets = get_packets()
    tcp = udp = icmp = other = 0

    for packet in packets:
        proto = packet["protocol"]
        if proto == "TCP": tcp += 1
        elif proto == "UDP": udp += 1
        elif proto == "ICMP": icmp += 1
        else: other += 1

    return jsonify({"total": len(packets), "tcp": tcp, "udp": udp, "icmp": icmp, "other": other})

@app.route("/api/sniffer/search")
def search_packets():
    ip = request.args.get("ip")
    packets = get_packets()
    result = [packet for packet in packets if ip in packet["src"] or ip in packet["dst"]]
    return jsonify(result)

@app.route("/export_packets")
def export_packets():
    packets = get_packets()
    filename = os.path.join(REPORT_FOLDER, "captured_packets.csv")

    with open(filename, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["Time", "Source", "Destination", "Protocol", "Length"])
        for p in packets:
            writer.writerow([p["time"], p["src"], p["dst"], p["protocol"], p["length"]])

    add_log(session["username"], "Exported Packet Capture")
    return send_file(filename, as_attachment=True)

# ==========================================
# PASSWORD STRENGTH ANALYZER API
# ==========================================

@app.route("/api/password/check", methods=["POST"])
def password_check():
    if not login_required():
        return jsonify({"status": "error"})

    password = request.json.get("password", "")
    score = 0
    suggestions = []

    if len(password) >= 8: score += 20
    else: suggestions.append("Use at least 8 characters.")

    if len(password) >= 12: score += 10
    if any(c.isupper() for c in password): score += 20
    else: suggestions.append("Add uppercase letters.")

    if any(c.islower() for c in password): score += 15
    else: suggestions.append("Add lowercase letters.")

    if any(c.isdigit() for c in password): score += 15
    else: suggestions.append("Add numbers.")

    if any(not c.isalnum() for c in password): score += 20
    else: suggestions.append("Use special characters.")

    if score < 40: strength = "WEAK"
    elif score < 70: strength = "MEDIUM"
    elif score < 90: strength = "STRONG"
    else: strength = "VERY STRONG"

    add_log(session["username"], "Password Strength Checked")
    return jsonify({"password_strength": strength, "score": score, "suggestions": suggestions})

@app.route("/api/password/entropy", methods=["POST"])
def password_entropy():
    password = request.json.get("password", "")
    charset = 0

    if any(c.islower() for c in password): charset += 26
    if any(c.isupper() for c in password): charset += 26
    if any(c.isdigit() for c in password): charset += 10
    if any(not c.isalnum() for c in password): charset += 32

    if charset == 0:
        entropy = 0
    else:
        import math
        entropy = round(len(password) * math.log2(charset), 2)

    return jsonify({"entropy": entropy})

# ==========================================
# PREVIOUS FALLBACK MOCK AI ROUTE
# ==========================================
@app.route("/api/ai_mock", methods=["POST"])
def ai_copilot_api():
    if not login_required():
        return jsonify({"reply": "Login Required."})

    question = request.json.get("question", "").lower()
    if "hello" in question or "hi" in question: answer = "Hello Operator. CyberForge AI is online."
    elif "nmap" in question: answer = "Nmap is used for host discovery and vulnerability assessment."
    elif "sql" in question: answer = "SQL Injection allows attackers to manipulate backend databases."
    elif "xss" in question: answer = "Cross Site Scripting injects malicious JavaScript into web pages."
    else: answer = "CyberForge AI supports basic cybersecurity queries."

    return jsonify({"reply": answer})

@app.route("/api/system_health")
def system_health():
    if not login_required():
        return jsonify({"status": "error"})

    return jsonify({
        "server": "ONLINE",
        "packet_sniffer": "RUNNING" if capture_running else "STOPPED",
        "database": "CONNECTED",
        "ai": "ONLINE",
        "threat_level": get_threat_level(),
        "security_score": security_score()
    })

@app.route("/generate_report")
def generate_report():
    if not login_required():
        return redirect("/login")

    username = request.args.get("username", session.get("username"))
    if not username:
        return redirect("/login")

    conn = get_db()
    cursor = conn.cursor()

    # 1. Fetch user details
    cursor.execute("SELECT email FROM users WHERE username=?", (username,))
    user_row = cursor.fetchone()
    email = user_row["email"] if user_row else "Unknown Email"

    # 2. Fetch activity logs/tasks performed by the user
    cursor.execute("SELECT activity, timestamp FROM activity_logs WHERE username=? ORDER BY id DESC", (username,))
    logs = cursor.fetchall()
    action_count = len(logs)

    # 2b. Fetch academy lab progress completed by the user
    cursor.execute("""
        SELECT al.title, al.xp_value, lp.flag 
        FROM lab_progress lp 
        JOIN academy_lessons al ON lp.lab_id = al.id 
        WHERE lp.username=? AND lp.completed=1
    """, (username,))
    completed_labs = cursor.fetchall()
    total_xp = sum(row["xp_value"] for row in completed_labs)

    # 3. Calculate scores of that user
    user_security_score = max(0, 100 - action_count)

    # 4. Generate CSV file
    import csv
    filename = os.path.join(REPORT_FOLDER, f"CyberForge_Report_{username}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    
    try:
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            
            # Header Info
            writer.writerow(["CYBERFORGE SECURITY OPERATIONS CENTER - USER REPORT"])
            writer.writerow([])
            
            # User Summary & Performance Scores
            writer.writerow(["USER SUMMARY & PERFORMANCE SCORES"])
            writer.writerow(["Parameter", "Value"])
            writer.writerow(["Username", username])
            writer.writerow(["Email Address", email])
            writer.writerow(["Total Actions Logged", action_count])
            writer.writerow(["Account Security Score", f"{user_security_score}/100"])
            writer.writerow(["Total Academy XP Gained", f"{total_xp} XP"])
            writer.writerow([])
            
            # Academy Training Progress
            writer.writerow(["ACADEMY TRAINING PROGRESS"])
            writer.writerow(["Academy Lab Title", "XP Gained", "Flag Captured"])
            for row in completed_labs:
                writer.writerow([row["title"], f"{row['xp_value']} XP", row["flag"]])
            writer.writerow(["Total Academy XP", f"{total_xp} XP"])
            writer.writerow([])
            
            # Tasks Performed
            writer.writerow(["TASKS PERFORMED / ACTIVITY LOGS"])
            writer.writerow(["Activity Action Description", "Timestamp Logged"])
            for row in logs:
                writer.writerow([row["activity"], row["timestamp"]])
    except Exception as e:
        print(f"Error writing CSV file: {e}")

    # 5. Save report details in db
    cursor.execute("INSERT INTO reports (username, filename) VALUES (?,?)", (session["username"], filename))
    conn.commit()
    conn.close()

    add_log(session["username"], f"Generated Security Report for {username}")
    return send_file(filename, as_attachment=True, download_name=os.path.basename(filename))

@app.route("/report_history")
def report_history():
    if not login_required():
        return redirect("/login")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reports ORDER BY id DESC")
    reports = cursor.fetchall()
    conn.close()
    return render_template("report.html", reports=reports)

@app.errorhandler(404)
def page_not_found(error):
    return render_template("404.html"), 404

@app.errorhandler(500)
def server_error(error):
    return render_template("500.html"), 500

@app.route("/awareness")
def safety_awareness():
    if not login_required():
        return redirect("/login")
    return render_template("awareness.html", username=session["username"])

# ========================================================
# KALI LINUX VM INTERFACE INTEGRATION METADATA
# ========================================================

AUTHORIZED_KALI_IPS = ["192.168.24.128", "127.0.0.1", "192.168.0.108"]  

@app.route("/api/kali/execute", methods=["POST"])
def remote_kali_trigger():
    client_ip = request.remote_addr
    if client_ip not in AUTHORIZED_KALI_IPS:
        return jsonify({"status": "error", "message": "Access Denied"}), 403

    data = request.get_json() or {}
    action_performed = data.get("action", "none")

    if action_performed == "nmap_scan":
        current_lab_attack_state["active_incident"] = "nmap"
        add_log("Kali_VM", "External port sweep reconnaissance tracked from Kali interface.")
    elif action_performed == "hydra_ssh":
        current_lab_attack_state["active_incident"] = "hydra"
        add_log("Kali_VM", "High-frequency password guessing sweep logged on port 22.")
    elif action_performed == "trigger_compromise":
        current_lab_attack_state["active_incident"] = "msfconsole"
        add_log("Kali_VM", "Exploit payload verified.")
    elif action_performed == "reset_lab":
        current_lab_attack_state["active_incident"] = "none"

    return jsonify({"status": "success", "node_ip": client_ip, "current_victim_state": current_lab_attack_state["active_incident"]})

@app.route("/google3daaca8914d61e87.html")
def google_site_verification():
    return "google-site-verification: google3daaca8914d61e87.html"

# ==========================================

# RUN APPLICATION (VIA SOCKETIO COMPATIBILITY)
# ==========================================
if __name__ == "__main__":
    socketio.run(
        app,
        debug=True,
        host="0.0.0.0",
        port=5000,
        allow_unsafe_werkzeug=True
    )