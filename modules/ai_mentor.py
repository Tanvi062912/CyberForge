from flask import Blueprint, render_template, request, jsonify, session, redirect
import sqlite3
import os
import json
import datetime
from database import get_db

ai_mentor_blueprint = Blueprint('ai_mentor', __name__)

def login_required():
    return "username" in session

# ---------------- DYNAMIC LLM CONNECTORS ----------------

def query_llm(system_prompt, user_prompt):
    # Try Groq first, then Gemini
    api_key = os.environ.get("GROQ_API_KEY")
    if api_key and not api_key.startswith("AQ."):
        import requests
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.5,
            "max_tokens": 1024,
            "stream": False
        }
        try:
            response = requests.post(url, json=payload, timeout=8)
            if response.status_code == 200:
                result = response.json()
                return result.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception as e:
            print(f"AI Mentor Groq error: {e}")

    # Fallback to Gemini
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key and not gemini_key.startswith("AQ."):
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel(model_name='gemini-3.5-flash', system_instruction=system_prompt)
            response = model.generate_content(user_prompt)
            return response.text
        except Exception as e:
            print(f"AI Mentor Gemini error: {e}")
            
    return None

# ---------------- STATIC CLUES FOR HINT ENGINE ----------------

STATIC_HINTS = {
    "phishing_attack": {
        1: {
            1: "Look closely at the email sender address domain. Compare it to the official domain of FakeBank.",
            2: "Analyze the headers. You will find that the email originates from alert_sec@fakebank-update.com rather than fakebank.com.",
            3: "The Indicator of Compromise is the phishing domain 'fakebank-update.com'."
        },
        2: {
            1: "Operators download attachments into the public storage directories.",
            2: "Look at the files inside `database/victim_storage/`. Identify files ending with double extensions or executables.",
            3: "The file is 'invoice.pdf.exe', which is a malicious executable masked as a PDF."
        },
        3: {
            1: "Process lists on the victim workspace display running applications.",
            2: "A Trojan process will execute persistently to maintain connection access.",
            3: "The rogue backdoor process name is 'backdoor_svc.exe'."
        },
        4: {
            1: "Look at the packets sniffer console logs. Filter by protocols or search IPs.",
            2: "Filter traffic for HTTP payloads or C2 command beaconing signals.",
            3: "The Command & Control beacon target IP is '192.168.24.131' on port 4444."
        }
    },
    "sql_injection": {
        1: {
            1: "Examine web server request parameters on page endpoints.",
            2: "Look for characters like single quotes or UNION keyword injections in the arguments.",
            3: "The SQL Injection target URL is page parameter '?page='."
        }
    }
}

# ---------------- FLASK ROUTES ----------------

@ai_mentor_blueprint.route("/ai_mentor")
def index():
    if not login_required():
        return redirect("/login")
        
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Fetch active scenario info
    cursor.execute("""
        SELECT us.*, s.name as scenario_name, s.objectives 
        FROM user_scenarios us
        JOIN scenarios s ON us.scenario_id = s.scenario_id
        WHERE us.username=? AND us.status='STARTED'
        LIMIT 1
    """, (session["username"],))
    active = cursor.fetchone()
    
    active_scenario_name = None
    active_step = None
    if active:
        active_scenario_name = active["scenario_name"]
        active_step = active["current_step"]
        
    # 2. Fetch learning recommendations
    cursor.execute("SELECT * FROM learning_recommendations WHERE username=? ORDER BY id DESC LIMIT 5", (session["username"],))
    recs = [dict(row) for row in cursor.fetchall()]
    
    # 3. Fetch generated scenarios
    cursor.execute("SELECT * FROM ai_generated_scenarios WHERE username=? ORDER BY id DESC LIMIT 5", (session["username"],))
    gen_scenarios = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return render_template(
        "ai_mentor.html",
        username=session["username"],
        active_scenario=active_scenario_name,
        active_step=active_step,
        recommendations=recs,
        gen_scenarios=gen_scenarios
    )

@ai_mentor_blueprint.route("/api/mentor/hint", methods=["POST"])
def get_hint():
    if not login_required():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
        
    data = request.get_json() or {}
    level = int(data.get("level", 1)) # Level 1, 2, or 3
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get active scenario
    cursor.execute("""
        SELECT us.*, s.name as scenario_name 
        FROM user_scenarios us
        JOIN scenarios s ON us.scenario_id = s.scenario_id
        WHERE us.username=? AND us.status='STARTED'
        LIMIT 1
    """, (session["username"],))
    active = cursor.fetchone()
    
    if not active:
        conn.close()
        return jsonify({"status": "error", "message": "No active scenario found to provide hints for."}), 400
        
    scenario_id = active["scenario_id"]
    current_step = active["current_step"]
    
    # 1. Fetch static hint if available
    hint_text = None
    if scenario_id in STATIC_HINTS and current_step in STATIC_HINTS[scenario_id]:
        hint_text = STATIC_HINTS[scenario_id][current_step].get(level)
        
    # 2. Attempt LLM hint generation
    system_prompt = (
        "You are the CyberForge AI Mentor. Your task is to provide progressive, educational hints "
        "to a cybersecurity student solving a range challenge. Be concise, technical, and encourage "
        "critical thinking. Do not give the complete flag directly, but guide them."
    )
    
    user_prompt = (
        f"The student is working on the scenario '{active['scenario_name']}' "
        f"and is currently stuck on Step {current_step}. "
        f"Please provide a Level {level} progressive hint. "
        f"Level 1: Small clue. Level 2: Specific clue. Level 3: Strong guidance."
    )
    
    llm_hint = query_llm(system_prompt, user_prompt)
    if llm_hint:
        hint_text = llm_hint
        
    if not hint_text:
        hint_text = f"Keep investigating step #{current_step}. Ensure you inspect access logs, victim storage directories, and system processes."
        
    # Log session feedback
    cursor.execute("""
        INSERT INTO mentor_sessions (username, scenario_id)
        VALUES (?, ?)
    """, (session["username"], scenario_id))
    session_id = cursor.lastrowid
    
    cursor.execute("""
        INSERT INTO mentor_feedback (session_id, username, evaluation_type, query, feedback, score)
        VALUES (?, ?, 'hint', ?, ?, 0)
    """, (session_id, session["username"], f"Hint Level {level} on step {current_step}", hint_text))
    
    conn.commit()
    conn.close()
    
    return jsonify({"status": "success", "hint": hint_text, "level": level})

@ai_mentor_blueprint.route("/api/mentor/evaluate", methods=["POST"])
def evaluate_findings():
    if not login_required():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
        
    data = request.get_json() or {}
    findings = data.get("findings", "").strip()
    
    if not findings:
        return jsonify({"status": "error", "message": "Findings text is required"}), 400
        
    conn = get_db()
    cursor = conn.cursor()
    
    # Get active scenario
    cursor.execute("""
        SELECT us.*, s.name as scenario_name, s.expected_findings 
        FROM user_scenarios us
        JOIN scenarios s ON us.scenario_id = s.scenario_id
        WHERE us.username=? AND us.status='STARTED'
        LIMIT 1
    """, (session["username"],))
    active = cursor.fetchone()
    
    if not active:
        conn.close()
        return jsonify({"status": "error", "message": "No active scenario found to evaluate findings against."}), 400
        
    scenario_id = active["scenario_id"]
    scenario_name = active["scenario_name"]
    expected_findings = active["expected_findings"]
    
    # Default offline evaluation fallback
    score = 50
    accuracy_feedback = "Your findings describe typical anomalies, but lack specific indicators."
    completeness_feedback = "Ensure you specify target domains, malicious filenames, and remote C2 IP markers."
    recs = "Review social engineering packets and malware persistence modules inside the academy."
    
    # Smart offline parsing
    findings_lower = findings.lower()
    matches = 0
    if "invoice.pdf.exe" in findings_lower: matches += 1
    if "192.168.24.131" in findings_lower: matches += 1
    if "backdoor_svc.exe" in findings_lower: matches += 1
    if "fakebank-update.com" in findings_lower: matches += 1
    
    if scenario_id == "phishing_attack":
        if matches == 4:
            score = 100
            accuracy_feedback = "Perfect! You identified the phishing domain, download vector, Trojan service, and connection callback beacon IP."
            completeness_feedback = "Findings are fully complete and include all required Indicators of Compromise."
            recs = "Excellent work. Proceed to Incident Response and report exporting stages."
        elif matches > 1:
            score = 75
            accuracy_feedback = "High accuracy. You successfully localized major attack indicators."
            completeness_feedback = "Minor details missing. Verify the C2 destination IP or malware filename."
            recs = "Review packet sniffing academy module to inspect plaintext traffic patterns."
        else:
            score = 40
            # Deduct points for incorrect findings
            try:
                from modules.gamification import deduct_points
                deduct_points(session["username"], 10, "Submitted incomplete scenario findings evaluation")
            except Exception:
                pass
    
    # LLM evaluation if online
    system_prompt = (
        "You are the CyberForge AI Mentor. Evaluate user findings. "
        "Respond ONLY in valid JSON matching this schema, without backticks or preambles:\n"
        "{\n"
        '  "score": 85,\n'
        '  "accuracy_feedback": "Your evaluation details...",\n'
        '  "completeness_feedback": "Your evaluation details...",\n'
        '  "recommendations": "Recommend specific topics..."\n'
        "}"
    )
    
    user_prompt = (
        f"Scenario Name: {scenario_name}\n"
        f"Expected Findings: {expected_findings}\n"
        f"User Submitted Findings: {findings}\n"
    )
    
    llm_res = query_llm(system_prompt, user_prompt)
    if llm_res:
        try:
            # Clean JSON indicators
            clean_res = llm_res.strip()
            if clean_res.startswith("```json"): clean_res = clean_res[7:]
            if clean_res.endswith("```"): clean_res = clean_res[:-3]
            clean_res = clean_res.strip()
            
            parsed = json.loads(clean_res)
            score = int(parsed.get("score", score))
            accuracy_feedback = parsed.get("accuracy_feedback", accuracy_feedback)
            completeness_feedback = parsed.get("completeness_feedback", completeness_feedback)
            recs = parsed.get("recommendations", recs)
        except Exception as e:
            print(f"Failed to parse LLM evaluation JSON: {e}")
            
    # Save session
    cursor.execute("INSERT INTO mentor_sessions (username, scenario_id) VALUES (?, ?)", (session["username"], scenario_id))
    session_id = cursor.lastrowid
    
    cursor.execute("""
        INSERT INTO mentor_feedback (session_id, username, evaluation_type, query, feedback, score)
        VALUES (?, ?, 'findings', ?, ?, ?)
    """, (session_id, session["username"], findings, f"Accuracy: {accuracy_feedback} | Completeness: {completeness_feedback}", score))
    
    # Write learning recommendation in table
    cursor.execute("""
        INSERT INTO learning_recommendations (username, topic, recommendation)
        VALUES (?, ?, ?)
    """, (session["username"], scenario_name, recs))
    
    # Award gamification XP for completing investigation evaluation
    try:
        from modules.gamification import award_xp
        if score >= 70:
            award_xp(session["username"], 50, 50, f"Passed scenario evaluation: {scenario_name} (Score: {score}%)")
        else:
            from modules.gamification import deduct_points
            deduct_points(session["username"], 10, f"Failed scenario findings evaluation: {scenario_name}")
    except Exception:
        pass
        
    conn.commit()
    conn.close()
    
    return jsonify({
        "status": "success",
        "score": score,
        "accuracy_feedback": accuracy_feedback,
        "completeness_feedback": completeness_feedback,
        "recommendations": recs
    })

@ai_mentor_blueprint.route("/api/mentor/generate_scenario", methods=["POST"])
def generate_scenario():
    if not login_required():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
        
    data = request.get_json() or {}
    stype = data.get("type", "phishing") # phishing, malware, insider_threat, web_attack, network_intrusion
    
    # Offline templates
    templates = {
        "phishing": {
            "name": "Spear Phishing Account Compromise",
            "difficulty": "Easy",
            "objectives": "Isolate fake domain domains, identify link attachments, verify logons.",
            "attack_chain": "Email -> Link Clicked -> Fake Portal Logon -> Cookie Exfiltrated",
            "expected_findings": "Phishing portal IP, stolen admin account name"
        },
        "malware": {
            "name": "Crypto Miner Persistence Execution",
            "difficulty": "Medium",
            "objectives": "Track high CPU processes, isolate miner executables, restrict external miner pool DNS requests.",
            "attack_chain": "Logon Exploitation -> Miner Executable Staged -> Persistence Registry Hook -> Outbound Mining IP Connection",
            "expected_findings": "Miner executable filename, mining pool IP address"
        },
        "insider_threat": {
            "name": "Unauthorized Database Dump exfiltration",
            "difficulty": "Hard",
            "objectives": "Analyze file system access records, detect mass directory copy, isolate unauthorized SFTP download logs.",
            "attack_chain": "Local User Token Privilege Escalation -> Database Dump -> Archive Packaging -> External File Server Upload",
            "expected_findings": "Compromised employee database account user name, SFTP destination server IP"
        },
        "web_attack": {
            "name": "XSS Cookie Theft Penetration",
            "difficulty": "Medium",
            "objectives": "Locate vulnerable guest comment section, extract reflected scripting triggers, audit admin authentication logs.",
            "attack_chain": "Cross Site Scripting Payload injection -> Victim Session Hijacked -> Admin Console Intrusion",
            "expected_findings": "Vulnerable comment input page URL, attacker cookie listener server port"
        },
        "network_intrusion": {
            "name": "IDS SYN Flood Scan Sweep",
            "difficulty": "Easy",
            "objectives": "Configure firewall traffic drop matrices, trace sweeping host vectors, inspect open port logs.",
            "attack_chain": "SYN Flood Port Scan -> Open SSH Service Detection -> Password Dictionary Brute Force",
            "expected_findings": "Sweeping attacker IP address, SSH cracked target host"
        }
    }
    
    sc_data = templates.get(stype, templates["phishing"])
    
    # LLM custom generation if online
    system_prompt = (
        "You are the CyberForge AI Mentor. Generate a custom, realistic cybersecurity training scenario. "
        "Respond ONLY in valid JSON matching this schema, without backticks or preambles:\n"
        "{\n"
        '  "name": "Scenario Name...",\n'
        '  "difficulty": "Easy/Medium/Hard",\n'
        '  "objectives": "Detail the objectives...",\n'
        '  "attack_chain": "Detail the attack chain...",\n'
        '  "expected_findings": "Detail expected indicators..."\n'
        "}"
    )
    
    user_prompt = f"Please generate a custom scenario of type: {stype}."
    
    llm_res = query_llm(system_prompt, user_prompt)
    if llm_res:
        try:
            clean_res = llm_res.strip()
            if clean_res.startswith("```json"): clean_res = clean_res[7:]
            if clean_res.endswith("```"): clean_res = clean_res[:-3]
            clean_res = clean_res.strip()
            
            parsed = json.loads(clean_res)
            sc_data = {
                "name": parsed.get("name", sc_data["name"]),
                "difficulty": parsed.get("difficulty", sc_data["difficulty"]),
                "objectives": parsed.get("objectives", sc_data["objectives"]),
                "attack_chain": parsed.get("attack_chain", sc_data["attack_chain"]),
                "expected_findings": parsed.get("expected_findings", sc_data["expected_findings"])
            }
        except Exception as e:
            print(f"Failed to parse custom generated scenario JSON: {e}")
            
    # Write to generated scenario database
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO ai_generated_scenarios (username, scenario_type, name, difficulty, objectives, attack_chain, expected_findings)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (session["username"], stype, sc_data["name"], sc_data["difficulty"], sc_data["objectives"], sc_data["attack_chain"], sc_data["expected_findings"]))
    
    # Award gamification XP for requesting scenario generation
    try:
        from modules.gamification import award_xp
        award_xp(session["username"], 10, 10, f"Generated a custom {stype} scenario with AI Mentor")
    except Exception:
        pass
        
    conn.commit()
    conn.close()
    
    return jsonify({"status": "success", "scenario": sc_data})

@ai_mentor_blueprint.route("/api/mentor/recommendations")
def get_recommendations():
    if not login_required():
        return jsonify({"status": "error"}), 401
        
    conn = get_db()
    cursor = conn.cursor()
    
    # Fetch incomplete labs to make recommendations
    # Fetch all seeded lessons
    cursor.execute("SELECT * FROM academy_lessons")
    lessons = cursor.fetchall()
    
    # Fetch completed labs
    cursor.execute("SELECT lab_id FROM lab_progress WHERE username=? AND completed=1", (session["username"],))
    completed_ids = {row["lab_id"] for row in cursor.fetchall()}
    
    recs = []
    for l in lessons:
        if l["id"] not in completed_ids:
            recs.append({
                "lesson_key": l["lesson_key"],
                "title": l["title"],
                "xp": l["xp_value"],
                "recommendation": f"Complete this academy training module to reinforce your defensive skills in {l['title']}."
            })
            
    conn.close()
    
    return jsonify({"status": "success", "recommendations": recs[:3]})
