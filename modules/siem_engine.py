from flask import Blueprint, render_template, jsonify, session, redirect, request
import sqlite3
import random
import datetime
import threading
import time
from database import get_db

siem_blueprint = Blueprint('siem_engine', __name__)

# Global reference to SocketIO instance, set on startup from app.py
socketio_instance = None

def set_socketio(socketio):
    global socketio_instance
    socketio_instance = socketio

def login_required():
    return "username" in session

# ---------------- CORRELATION UTILS & RULES ----------------

def run_correlation_engine(conn):
    cursor = conn.cursor()
    
    # 1. Fetch last 15 events
    cursor.execute("SELECT * FROM events ORDER BY id DESC LIMIT 15")
    recent_events = [dict(row) for row in cursor.fetchall()]
    recent_events.reverse() # Order from oldest to newest for analysis
    
    if len(recent_events) < 2:
        return
        
    # Check Rule 1: Brute Force Correlation
    # 5 failed logins + successful login from same IP
    # Let's check groups of events
    ips = {}
    for ev in recent_events:
        ip = ev["src_ip"]
        if not ip: continue
        if ip not in ips:
            ips[ip] = []
        ips[ip].append(ev)
        
    for ip, evs in ips.items():
        # Look for 5 FAILED followed by 1 SUCCESSFUL
        failed_count = 0
        brute_triggered = False
        for e in evs:
            if e["event_type"] == "FAILED_LOGIN":
                failed_count += 1
            elif e["event_type"] == "SUCCESSFUL_LOGIN":
                if failed_count >= 5:
                    brute_triggered = True
                    break
                failed_count = 0 # Reset
            else:
                # Other event type doesn't break failed chain necessarily, but let's keep it simple
                pass
                
        if brute_triggered:
            # Check if this alert was already raised in the last 2 minutes to prevent duplicates
            cursor.execute("""
                SELECT COUNT(*) FROM alerts 
                WHERE title = 'Brute Force Correlation Alert' 
                AND description LIKE ? 
                AND timestamp >= datetime('now', '-2 minutes')
            """, (f"%{ip}%",))
            if cursor.fetchone()[0] == 0:
                # Trigger Alert
                cursor.execute("""
                    INSERT INTO alerts (rule_id, title, description, severity)
                    VALUES (1, 'Brute Force Correlation Alert', ?, 'High')
                """, (f"Detected 5+ failed logons followed by successful logon from source IP {ip}.",))
                
                # Trigger Incident
                cursor.execute("""
                    INSERT INTO incidents (title, description, severity, status)
                    VALUES ('Correlated Brute Force Compromise', ?, 'High', 'ACTIVE')
                """, (f"Host authentication logs indicate successful brute force intrusion from external IP {ip}.",))
                conn.commit()
                
                # Emit socket notification
                emit_siem_alert('High', 'Brute Force Correlation Alert', f"Multiple login failures followed by successful authentication from IP {ip}")

    # Check Rule 2: Malware Infection Linker
    # Malicious DNS + suspicious process on same host IP
    host_events = {}
    for ev in recent_events:
        ip = ev["src_ip"] # Source IP acts as the infected host IP
        if not ip: continue
        if ip not in host_events:
            host_events[ip] = []
        host_events[ip].append(ev["event_type"])
        
    for ip, types in host_events.items():
        if "MALICIOUS_DNS" in types and "SUSPICIOUS_PROCESS" in types:
            # Check if this alert was already raised in last 2 minutes
            cursor.execute("""
                SELECT COUNT(*) FROM alerts 
                WHERE title = 'Possible Malware Infection Alert' 
                AND description LIKE ? 
                AND timestamp >= datetime('now', '-2 minutes')
            """, (f"%{ip}%",))
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    INSERT INTO alerts (rule_id, title, description, severity)
                    VALUES (2, 'Possible Malware Infection Alert', ?, 'Critical')
                """, (f"Correlated malicious DNS request query lookup and unsigned process execution on host {ip}.",))
                
                cursor.execute("""
                    INSERT INTO incidents (title, description, severity, status)
                    VALUES ('Host C2 Malware Infection', ?, 'Critical', 'ACTIVE')
                """, (f"Endpoint {ip} displays indicators of active backdoor persistence and Command & Control callback beaconing.",))
                conn.commit()
                
                emit_siem_alert('Critical', 'Possible Malware Infection Alert', f"Malicious DNS callback and rogue service process detected on endpoint {ip}")

    # Check Rule 3: Reconnaissance Mapping
    # Port scan + web attack from same source IP
    attacker_events = {}
    for ev in recent_events:
        ip = ev["src_ip"]
        if not ip: continue
        if ip not in attacker_events:
            attacker_events[ip] = []
        attacker_events[ip].append(ev["event_type"])
        
    for ip, types in attacker_events.items():
        if "PORT_SCAN" in types and ("SQL_INJECTION" in types or "XSS_ATTACK" in types):
            # Check duplicates
            cursor.execute("""
                SELECT COUNT(*) FROM alerts 
                WHERE title = 'Reconnaissance Mapping Alert' 
                AND description LIKE ? 
                AND timestamp >= datetime('now', '-2 minutes')
            """, (f"%{ip}%",))
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    INSERT INTO alerts (rule_id, title, description, severity)
                    VALUES (3, 'Reconnaissance Mapping Alert', ?, 'Medium')
                """, (f"Detected external port sweep reconnaissance followed by web exploitation attempts from source IP {ip}.",))
                
                cursor.execute("""
                    INSERT INTO incidents (title, description, severity, status)
                    VALUES ('Active Recon & Penetration Sweep', ?, 'Medium', 'ACTIVE')
                """, (f"External scanning host {ip} has escalated to targeting web application vulnerabilities.",))
                conn.commit()
                
                emit_siem_alert('Medium', 'Reconnaissance Mapping Alert', f"Port scan followed by web application exploitation detected from source {ip}")

def emit_siem_event(ev_data):
    if socketio_instance:
        try:
            socketio_instance.emit('new_siem_event', ev_data)
        except Exception as e:
            print(f"Socket emit event error: {e}")

def emit_siem_alert(severity, title, desc):
    if socketio_instance:
        try:
            socketio_instance.emit('new_siem_alert', {
                'severity': severity,
                'title': title,
                'description': desc,
                'timestamp': datetime.datetime.now().strftime('%H:%M:%S')
            })
        except Exception as e:
            print(f"Socket emit alert error: {e}")

# Background worker loop
def event_generator_loop():
    print("[SIEM] Background Event Generator & Correlation Worker Started.")
    
    # Event library to pick from
    sources = ["AuthService", "IDS", "DNS", "Firewall", "Host"]
    event_templates = [
        {"source": "AuthService", "type": "FAILED_LOGIN", "desc": "Failed logon attempt for 'admin' user profile", "src_ip": "192.168.10.45", "dst_ip": "10.0.0.12", "severity": "Low"},
        {"source": "AuthService", "type": "SUCCESSFUL_LOGIN", "desc": "Successful administrative login session verified", "src_ip": "192.168.10.45", "dst_ip": "10.0.0.12", "severity": "Medium"},
        {"source": "IDS", "type": "PORT_SCAN", "desc": "TCP Port sweep scanning matching SYN flood signature", "src_ip": "192.168.1.102", "dst_ip": "10.0.0.12", "severity": "Medium"},
        {"source": "IDS", "type": "SQL_INJECTION", "desc": "SQL Injection payload signature UNION SELECT block matched", "src_ip": "192.168.1.102", "dst_ip": "10.0.0.15", "severity": "High"},
        {"source": "IDS", "type": "XSS_ATTACK", "desc": "Cross Site Scripting reflected payload injection tracked", "src_ip": "192.168.1.103", "dst_ip": "10.0.0.15", "severity": "High"},
        {"source": "DNS", "type": "MALICIOUS_DNS", "desc": "DNS lookup anomaly: resolved blacklisted domain update-securecorp.com", "src_ip": "10.0.0.12", "dst_ip": "8.8.8.8", "severity": "High"},
        {"source": "Host", "type": "SUSPICIOUS_PROCESS", "desc": "Unsigned process binary 'backdoor_svc.exe' active in background", "src_ip": "10.0.0.12", "dst_ip": "0.0.0.0", "severity": "High"},
        {"source": "Firewall", "type": "TRAFFIC_DROP", "desc": "Inbound connection blocked on unauthorized port 4444", "src_ip": "185.220.101.4", "dst_ip": "10.0.0.15", "severity": "Low"}
    ]
    
    # We can inject specific sequences to guarantee correlation triggers occasionally
    force_sequence = []
    
    while True:
        try:
            time.sleep(8)
            
            # Select event
            if force_sequence:
                tmpl = force_sequence.pop(0)
            else:
                # Occassionally inject brute force or malware sequences to make it active!
                rand_val = random.random()
                if rand_val < 0.05:
                    # Inject Brute Force sequence
                    force_sequence = [
                        {"source": "AuthService", "type": "FAILED_LOGIN", "desc": "Failed logon attempt for 'administrator'", "src_ip": "192.168.10.45", "dst_ip": "10.0.0.12", "severity": "Low"},
                        {"source": "AuthService", "type": "FAILED_LOGIN", "desc": "Failed logon attempt for 'administrator'", "src_ip": "192.168.10.45", "dst_ip": "10.0.0.12", "severity": "Low"},
                        {"source": "AuthService", "type": "FAILED_LOGIN", "desc": "Failed logon attempt for 'administrator'", "src_ip": "192.168.10.45", "dst_ip": "10.0.0.12", "severity": "Low"},
                        {"source": "AuthService", "type": "FAILED_LOGIN", "desc": "Failed logon attempt for 'administrator'", "src_ip": "192.168.10.45", "dst_ip": "10.0.0.12", "severity": "Low"},
                        {"source": "AuthService", "type": "FAILED_LOGIN", "desc": "Failed logon attempt for 'administrator'", "src_ip": "192.168.10.45", "dst_ip": "10.0.0.12", "severity": "Low"},
                        {"source": "AuthService", "type": "SUCCESSFUL_LOGIN", "desc": "Successful administrative login session verified", "src_ip": "192.168.10.45", "dst_ip": "10.0.0.12", "severity": "Medium"}
                    ]
                    tmpl = force_sequence.pop(0)
                elif rand_val < 0.10:
                    # Inject Malware sequence
                    force_sequence = [
                        {"source": "DNS", "type": "MALICIOUS_DNS", "desc": "DNS lookup anomaly: resolved blacklisted domain update-securecorp.com", "src_ip": "10.0.0.12", "dst_ip": "8.8.8.8", "severity": "High"},
                        {"source": "Host", "type": "SUSPICIOUS_PROCESS", "desc": "Unsigned process binary 'backdoor_svc.exe' active in background", "src_ip": "10.0.0.12", "dst_ip": "0.0.0.0", "severity": "High"}
                    ]
                    tmpl = force_sequence.pop(0)
                else:
                    tmpl = random.choice(event_templates)
            
            # Write to database
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO events (event_source, event_type, description, src_ip, dst_ip, severity)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (tmpl["source"], tmpl["type"], tmpl["desc"], tmpl["src_ip"], tmpl["dst_ip"], tmpl["severity"]))
            conn.commit()
            
            # Fetch inserted event to get id and timestamp
            cursor.execute("SELECT * FROM events ORDER BY id DESC LIMIT 1")
            inserted = dict(cursor.fetchone())
            
            # Run correlation
            run_correlation_engine(conn)
            conn.close()
            
            # Emit event via SocketIO
            emit_siem_event(inserted)
            
        except Exception as e:
            print(f"[SIEM Engine Background Error]: {e}")

# Spin background worker daemon thread
background_thread = threading.Thread(target=event_generator_loop, daemon=True)
background_thread.start()

# ---------------- FLASK ROUTES ----------------

@siem_blueprint.route("/siem_center")
def index():
    if not login_required():
        return redirect("/login")
        
    conn = get_db()
    cursor = conn.cursor()
    
    # Fetch initial events, alerts, incidents
    cursor.execute("SELECT * FROM events ORDER BY id DESC LIMIT 15")
    events = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT 15")
    alerts = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM incidents ORDER BY id DESC LIMIT 15")
    incidents = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return render_template(
        "siem_center.html",
        username=session["username"],
        events=events,
        alerts=alerts,
        incidents=incidents
    )

@siem_blueprint.route("/api/siem/incidents/resolve/<int:id>", methods=["POST"])
def resolve_incident(id):
    if not login_required():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
        
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM incidents WHERE id=?", (id,))
    inc = cursor.fetchone()
    if not inc:
        conn.close()
        return jsonify({"status": "error", "message": "Incident not found"}), 404
        
    if inc["status"] == "RESOLVED":
        conn.close()
        return jsonify({"status": "error", "message": "Incident already resolved."}), 400
        
    cursor.execute("UPDATE incidents SET status='RESOLVED' WHERE id=?", (id,))
    conn.commit()
    conn.close()
    
    # Award gamification XP / points
    try:
        from modules.gamification import award_xp
        award_xp(session["username"], 30, 30, f"Resolved SIEM Incident #{id}: {inc['title']}")
    except Exception as e:
        print(f"Error awarding gamification XP: {e}")
        
    return jsonify({"status": "success", "message": f"Incident '{inc['title']}' marked as RESOLVED. +30 XP awarded!"})

@siem_blueprint.route("/api/siem/stats")
def siem_stats():
    if not login_required():
        return jsonify({"status": "error"}), 401
        
    conn = get_db()
    cursor = conn.cursor()
    
    # Get total count and severity distribution of alerts
    cursor.execute("SELECT COUNT(*) FROM events")
    total_events = cursor.fetchone()[0]
    
    cursor.execute("SELECT severity, COUNT(*) as count FROM alerts GROUP BY severity")
    alerts_distribution = {row["severity"]: row["count"] for row in cursor.fetchall()}
    
    cursor.execute("SELECT status, COUNT(*) as count FROM incidents GROUP BY status")
    incidents_distribution = {row["status"]: row["count"] for row in cursor.fetchall()}
    
    conn.close()
    
    return jsonify({
        "status": "success",
        "total_events": total_events,
        "alerts_severity": {
            "Low": alerts_distribution.get("Low", 0),
            "Medium": alerts_distribution.get("Medium", 0),
            "High": alerts_distribution.get("High", 0),
            "Critical": alerts_distribution.get("Critical", 0)
        },
        "incidents_status": incidents_distribution
    })
