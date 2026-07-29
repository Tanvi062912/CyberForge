import sqlite3
import os
from database import get_db

def initialize_addon_database():
    if not os.environ.get("VERCEL"):
        os.makedirs("database", exist_ok=True)
    conn = get_db()

    cursor = conn.cursor()

    # ---------------- FEATURE 1: SCENARIO ENGINE TABLES ----------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scenarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scenario_id TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        difficulty TEXT NOT NULL,
        objectives TEXT,
        attack_chain TEXT,
        expected_findings TEXT,
        completion_conditions TEXT,
        time_limit INTEGER
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scenario_steps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scenario_id TEXT NOT NULL,
        step_number INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        FOREIGN KEY (scenario_id) REFERENCES scenarios(scenario_id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_scenarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        scenario_id TEXT NOT NULL,
        status TEXT NOT NULL, -- 'STARTED', 'PAUSED', 'COMPLETED', 'FAILED'
        current_step INTEGER DEFAULT 1,
        started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        paused_at DATETIME,
        elapsed_time INTEGER DEFAULT 0, -- in seconds
        notes TEXT,
        FOREIGN KEY (scenario_id) REFERENCES scenarios(scenario_id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS evidence_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        scenario_id TEXT NOT NULL,
        step_number INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        collected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (scenario_id) REFERENCES scenarios(scenario_id)
    )
    """)

    # ---------------- FEATURE 2: GAMIFICATION TABLES ----------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_xp (
        username TEXT PRIMARY KEY,
        xp INTEGER DEFAULT 0,
        points INTEGER DEFAULT 0,
        skill_level TEXT DEFAULT 'Beginner Analyst',
        completed_labs INTEGER DEFAULT 0,
        incorrect_findings INTEGER DEFAULT 0,
        missed_evidence INTEGER DEFAULT 0
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS badges (
        badge_id TEXT PRIMARY KEY,
        name TEXT UNIQUE NOT NULL,
        description TEXT NOT NULL,
        icon TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_badges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        badge_id TEXT NOT NULL,
        earned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (badge_id) REFERENCES badges(badge_id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS leaderboard (
        username TEXT PRIMARY KEY,
        rank INTEGER,
        xp INTEGER,
        completed_labs INTEGER,
        accuracy REAL DEFAULT 100.0
    )
    """)

    # ---------------- FEATURE 3: SIEM CORRELATION ENGINE TABLES ----------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_source TEXT,
        event_type TEXT,
        description TEXT,
        src_ip TEXT,
        dst_ip TEXT,
        severity TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_id INTEGER,
        title TEXT,
        description TEXT,
        severity TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (rule_id) REFERENCES correlation_rules(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS incidents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        description TEXT,
        severity TEXT,
        status TEXT DEFAULT 'ACTIVE', -- 'ACTIVE', 'INVESTIGATING', 'RESOLVED'
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS correlation_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        description TEXT,
        rule_condition TEXT,
        severity TEXT
    )
    """)

    # ---------------- FEATURE 4: AI MENTOR TABLES ----------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS mentor_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        scenario_id TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS mentor_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        username TEXT NOT NULL,
        evaluation_type TEXT, -- 'findings', 'hint'
        query TEXT,
        feedback TEXT,
        score INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES mentor_sessions(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS learning_recommendations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        topic TEXT NOT NULL,
        recommendation TEXT NOT NULL,
        completed INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_generated_scenarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        scenario_type TEXT NOT NULL,
        name TEXT NOT NULL,
        difficulty TEXT NOT NULL,
        objectives TEXT NOT NULL,
        attack_chain TEXT NOT NULL,
        expected_findings TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ---------------- FEATURE 5: REPORT CENTER TABLES ----------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS report_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        template_type TEXT,
        content TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS generated_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        title TEXT NOT NULL,
        report_type TEXT NOT NULL,
        format TEXT NOT NULL,
        file_path TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ==========================================
    # SEED SEEDS
    # ==========================================

    # 1. Seed Scenarios
    scenarios_seed = [
        ("phishing_attack", "Phishing Email Attack Scenario", "Easy", 
         "Investigate an inbound phishing email attempt, analyze headers, locate the malicious file execution vector, track the simulated network connection attempt, and submit your incident report findings.",
         "Employee Email -> Invoice Attachment Downloaded -> Process Execution Spawned -> External Beacon IP Initiated -> Analyst Incident Verification",
         "Phishing sender IP (192.168.10.45), malicious filename (invoice.pdf.exe), callback beacon IP (192.168.24.131)",
         "Successful mitigation and documentation of findings in an incident report.",
         600),
        ("sql_injection", "SQL Injection Data Leak Scenario", "Medium",
         "Inspect web application logs for UNION-based injection payloads, isolate the compromised administrative table, locate the leaked database keys, and patch the input validation endpoint.",
         "Web Service Request Sweeping -> UNION SELECT Payload Injection -> User Credential Leak -> DB Flag Extraction -> Host Vulnerability Remediation",
         "Vulnerable parameter (?page=), dumped admin credentials hash, injection source IP",
         "Identify the SQL injection vector and submit the target flag to verify remediation.",
         900),
        ("ransomware_outbreak", "Ransomware Enterprise Escalation", "Hard",
         "A local workstation has run a suspicious executable. Identify the ransomware installation script, locate the encrypted file registry extension (.locked), isolate the SUID binaries enabling privilege escalation, and restore files from backup snapshots.",
         "Infected Payload Execution -> Cryptolocking Loop -> Local Token Elevation -> SUID Binary Search -> Restore Backup Snapshot",
         "SUID binary path (/usr/bin/find), encrypted file extension (.locked), NT AUTHORITY\SYSTEM access token",
         "Perform full defensive lab cleanup, delete backdoor service, and restore normal operations.",
         1200)
    ]

    # Clear default scenarios and steps to avoid duplicates on restarts
    default_scenario_ids = ('phishing_attack', 'sql_injection', 'ransomware_outbreak')
    cursor.execute("DELETE FROM scenario_steps WHERE scenario_id IN (?, ?, ?)", default_scenario_ids)
    cursor.execute("DELETE FROM scenarios WHERE scenario_id IN (?, ?, ?)", default_scenario_ids)

    for sid, name, diff, obj, chain, findings, cond, limit in scenarios_seed:
        cursor.execute("""
        INSERT OR IGNORE INTO scenarios (scenario_id, name, difficulty, objectives, attack_chain, expected_findings, completion_conditions, time_limit)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (sid, name, diff, obj, chain, findings, cond, limit))

    # Seed Steps for Phishing Scenario
    phishing_steps = [
        ("phishing_attack", 1, "Analyze Inbound Phishing Header", "Analyze the operator email inbox and find the suspicious sender domain."),
        ("phishing_attack", 2, "Isolate invoice.pdf.exe download", "Locate the downloaded payload in the victim folder registry."),
        ("phishing_attack", 3, "Detect Backdoor Process Initialization", "Identify the rogue backdoor_svc.exe running on the local host."),
        ("phishing_attack", 4, "Track Command & Control Beaconing", "Detect outgoing network frames attempting to beacon to C2 IP 192.168.24.131."),
        ("phishing_attack", 5, "Investigate SIEM Logon Alerts", "Analyze SIEM events log tracking failed brute force attempts followed by successful logon."),
        ("phishing_attack", 6, "Collect Incident Evidence", "Save screenshots and log strings mapping the attack sequence."),
        ("phishing_attack", 7, "Isolate Indicators of Compromise", "Enter target IPs and registry indicators in the investigation notes."),
        ("phishing_attack", 8, "Submit Report to SOC Team", "Generate and export your structured incident response findings report.")
    ]

    # Seed Steps for SQLi Scenario
    sqli_steps = [
        ("sql_injection", 1, "Examine Web Access Logs", "Identify the high volume of request scans on the web application."),
        ("sql_injection", 2, "Extract Database Dumping Flag", "Locate the injected UNION SELECT commands and find the dumped flag."),
        ("sql_injection", 3, "Verify Mitigation", "Verify that the web portal input parameter checks have been successfully updated.")
    ]

    # Seed Steps for Ransomware Scenario
    ransom_steps = [
        ("ransomware_outbreak", 1, "Locate Ransom Note Payload", "Isolate the cryptolock loop execution file and review file listings."),
        ("ransomware_outbreak", 2, "Escalate Local Privileges", "Audit NT AUTHORITY escalation and locate SUID binary helper permissions."),
        ("ransomware_outbreak", 3, "Perform Snapshot Recovery", "Run restoration commands to recover original workspace storage files.")
    ]

    for steps in [phishing_steps, sqli_steps, ransom_steps]:
        for sid, snum, title, desc in steps:
            cursor.execute("""
            INSERT OR IGNORE INTO scenario_steps (scenario_id, step_number, title, description)
            VALUES (?, ?, ?, ?)
            """, (sid, snum, title, desc))

    # 2. Seed Correlation Rules
    cursor.execute("DELETE FROM correlation_rules")
    rules_seed = [
        (1, "Brute Force Correlation", "Detects 5 failed logins followed by a successful login from the same source IP in a short duration.", "High"),
        (2, "Malware Infection Linker", "Correlates a known malicious command execution process with an outbound DNS request anomaly.", "Critical"),
        (3, "Reconnaissance Mapping", "Flags a high frequency port scanning event followed by web injection application server alerts.", "Medium")
    ]

    for rid, name, desc, sev in rules_seed:
        cursor.execute("""
        INSERT OR IGNORE INTO correlation_rules (id, name, description, severity)
        VALUES (?, ?, ?, ?)
        """, (rid, name, desc, sev))

    # 3. Seed Badges
    cursor.execute("DELETE FROM badges")
    badges_seed = [
        ("beginner_analyst", "Beginner Analyst", "Earned by completing your first cyber range scenario or defensive lab module.", "fa-baby"),
        ("threat_hunter", "Threat Hunter", "Earned by identifying and correlating multiple event alarms inside the SIEM center.", "fa-crosshairs"),
        ("soc_defender", "SOC Defender", "Successfully resolve critical incidents, maintaining the security health index above 80%.", "fa-user-shield"),
        ("packet_master", "Packet Master", "Captured and parsed unencrypted protocol packets using the packet sniffer tool.", "fa-network-wired"),
        ("malware_investigator", "Malware Investigator", "Completed the Malware Persistence or Ransomware Outbreak Range challenges.", "fa-virus-slash"),
        ("incident_responder", "Incident Responder", "Generated and exported incident and investigation reports from the Report Center.", "fa-file-shield"),
        ("cyberforge_elite", "CyberForge Elite", "Acquired a total of 1,000 XP inside the academy and scenario center.", "fa-crown")
    ]

    for bid, name, desc, icon in badges_seed:
        cursor.execute("""
        INSERT OR IGNORE INTO badges (badge_id, name, description, icon)
        VALUES (?, ?, ?, ?)
        """, (bid, name, desc, icon))

    # 4. Seed Report Templates
    cursor.execute("DELETE FROM report_templates")
    templates_seed = [
        ("incident_report_template", "incident", "Executive Summary, Attack Timeline, Identified Indicators of Compromise (IOCs), Findings Summary, Business Impact Analysis, Mitigation Recommendations."),
        ("investigation_report_template", "investigation", "Collected Forensic Evidence, Screenshot Artifacts, System Logs Metadata, Analyst Investigative Notes."),
        ("performance_report_template", "performance", "Completed Training Labs Progress, Current Analyst Skill Levels, Action Accuracy Rate, Earned Badges Portfolio.")
    ]

    for name, t_type, content in templates_seed:
        cursor.execute("""
        INSERT OR IGNORE INTO report_templates (name, template_type, content)
        VALUES (?, ?, ?)
        """, (name, t_type, content))

    conn.commit()
    conn.close()

if __name__ == "__main__":
    initialize_addon_database()
    print("CyberForge Addon Database Tables and Seed Data Initialized Successfully.")
