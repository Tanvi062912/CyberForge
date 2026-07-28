from flask import Blueprint, render_template, request, jsonify, session, redirect
import sqlite3
import datetime
from database import get_db

scenario_blueprint = Blueprint('scenario_engine', __name__)

def login_required():
    return "username" in session

def award_xp_helper(username, points_val, xp_val, reason):
    # Dynamic import to avoid circular dependency
    try:
        from modules.gamification import award_xp
        award_xp(username, points_val, xp_val, reason)
    except Exception as e:
        print(f"Error awarding XP inside scenario: {e}")

@scenario_blueprint.route("/scenario_engine")
def index():
    if not login_required():
        return redirect("/login")
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Get all scenarios
    cursor.execute("SELECT * FROM scenarios")
    scenarios = [dict(row) for row in cursor.fetchall()]
    
    # Get user's active scenario status
    cursor.execute("""
        SELECT us.*, s.name as scenario_name, s.difficulty, s.time_limit 
        FROM user_scenarios us
        JOIN scenarios s ON us.scenario_id = s.scenario_id
        WHERE us.username=? AND us.status IN ('STARTED', 'PAUSED')
        ORDER BY us.id DESC LIMIT 1
    """, (session["username"],))
    active_scenario = cursor.fetchone()
    if active_scenario:
        active_scenario = dict(active_scenario)
        # Calculate elapsed time dynamically if active and not paused
        if active_scenario["status"] == 'STARTED':
            # We track time_limit in seconds.
            pass
    
    # Get completed scenarios
    cursor.execute("""
        SELECT us.*, s.name as scenario_name, s.difficulty
        FROM user_scenarios us
        JOIN scenarios s ON us.scenario_id = s.scenario_id
        WHERE us.username=? AND us.status = 'COMPLETED'
        ORDER BY us.id DESC
    """, (session["username"],))
    completed_scenarios = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return render_template(
        "scenario_engine.html",
        username=session["username"],
        scenarios=scenarios,
        active_scenario=active_scenario,
        completed_scenarios=completed_scenarios
    )

@scenario_blueprint.route("/api/scenarios", methods=["GET"])
def list_scenarios():
    if not login_required():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM scenarios")
    scenarios = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({"status": "success", "scenarios": scenarios})

@scenario_blueprint.route("/api/scenario/start", methods=["POST"])
def start_scenario():
    if not login_required():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    data = request.get_json() or {}
    scenario_id = data.get("scenario_id")
    
    if not scenario_id:
        return jsonify({"status": "error", "message": "Scenario ID is required"}), 400
        
    conn = get_db()
    cursor = conn.cursor()
    
    # Check if scenario exists
    cursor.execute("SELECT * FROM scenarios WHERE scenario_id=?", (scenario_id,))
    scenario = cursor.fetchone()
    if not scenario:
        conn.close()
        return jsonify({"status": "error", "message": "Scenario not found"}), 404
        
    # Check if there is an active scenario
    cursor.execute("SELECT * FROM user_scenarios WHERE username=? AND status IN ('STARTED', 'PAUSED')", (session["username"],))
    if cursor.fetchone():
        conn.close()
        return jsonify({"status": "error", "message": "You already have an active scenario. Please end it before starting a new one."}), 400
        
    # Start the scenario
    cursor.execute("""
        INSERT INTO user_scenarios (username, scenario_id, status, current_step, started_at, elapsed_time, notes)
        VALUES (?, ?, 'STARTED', 1, CURRENT_TIMESTAMP, 0, '')
    """, (session["username"], scenario_id))
    conn.commit()
    conn.close()
    
    award_xp_helper(session["username"], 10, 10, f"Started scenario: {scenario['name']}")
    return jsonify({"status": "success", "message": f"Scenario {scenario['name']} started successfully!"})

@scenario_blueprint.route("/api/scenario/pause", methods=["POST"])
def pause_scenario():
    if not login_required():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM user_scenarios WHERE username=? AND status='STARTED'", (session["username"],))
    active = cursor.fetchone()
    if not active:
        conn.close()
        return jsonify({"status": "error", "message": "No active running scenario found to pause."}), 400
        
    # Calculate elapsed since started_at or paused_at
    cursor.execute("""
        UPDATE user_scenarios 
        SET status='PAUSED', paused_at=CURRENT_TIMESTAMP
        WHERE id=?
    """, (active["id"],))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Scenario paused."})

@scenario_blueprint.route("/api/scenario/resume", methods=["POST"])
def resume_scenario():
    if not login_required():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM user_scenarios WHERE username=? AND status='PAUSED'", (session["username"],))
    paused = cursor.fetchone()
    if not paused:
        conn.close()
        return jsonify({"status": "error", "message": "No paused scenario found to resume."}), 400
        
    cursor.execute("""
        UPDATE user_scenarios 
        SET status='STARTED', paused_at=NULL
        WHERE id=?
    """, (paused["id"],))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Scenario resumed."})

@scenario_blueprint.route("/api/scenario/end", methods=["POST"])
def end_scenario():
    if not login_required():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM user_scenarios WHERE username=? AND status IN ('STARTED', 'PAUSED')", (session["username"],))
    active = cursor.fetchone()
    if not active:
        conn.close()
        return jsonify({"status": "error", "message": "No active scenario found to end."}), 400
        
    cursor.execute("""
        UPDATE user_scenarios 
        SET status='FAILED', paused_at=NULL
        WHERE id=?
    """, (active["id"],))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Scenario terminated."})

@scenario_blueprint.route("/api/scenario/evidence", methods=["POST"])
def collect_evidence():
    if not login_required():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    data = request.get_json() or {}
    title = data.get("title", "").strip()
    description = data.get("description", "").strip()
    
    if not title or not description:
        return jsonify({"status": "error", "message": "Title and Description are required"}), 400
        
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM user_scenarios WHERE username=? AND status='STARTED'", (session["username"],))
    active = cursor.fetchone()
    if not active:
        conn.close()
        return jsonify({"status": "error", "message": "No active running scenario found to submit evidence for."}), 400
        
    scenario_id = active["scenario_id"]
    current_step = active["current_step"]
    
    # Save evidence item
    cursor.execute("""
        INSERT INTO evidence_items (username, scenario_id, step_number, title, description)
        VALUES (?, ?, ?, ?, ?)
    """, (session["username"], scenario_id, current_step, title, description))
    
    # Get total steps in scenario
    cursor.execute("SELECT COUNT(*) FROM scenario_steps WHERE scenario_id=?", (scenario_id,))
    total_steps = cursor.fetchone()[0]
    
    next_step = current_step + 1
    
    # Award points for evidence collection
    award_xp_helper(session["username"], 25, 25, f"Submitted evidence for Step {current_step} of {scenario_id}")
    
    is_completed = False
    if current_step >= total_steps:
        # Scenario Completed!
        cursor.execute("""
            UPDATE user_scenarios 
            SET status='COMPLETED', paused_at=NULL
            WHERE id=?
        """, (active["id"],))
        award_xp_helper(session["username"], 100, 100, f"Completed Scenario: {scenario_id}")
        is_completed = True
        msg = "Congratulations! You have completed all steps and resolved the incident scenario!"
    else:
        # Move to next step
        cursor.execute("""
            UPDATE user_scenarios 
            SET current_step=?
            WHERE id=?
        """, (next_step, active["id"]))
        msg = f"Evidence verified! Step {current_step} completed. Proceeding to Step {next_step}."
        
    conn.commit()
    conn.close()
    
    return jsonify({
        "status": "success",
        "message": msg,
        "is_completed": is_completed,
        "next_step": next_step if not is_completed else None
    })

@scenario_blueprint.route("/api/scenario/notes", methods=["POST"])
def save_notes():
    if not login_required():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    data = request.get_json() or {}
    notes = data.get("notes", "")
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_scenarios WHERE username=? AND status IN ('STARTED', 'PAUSED')", (session["username"],))
    active = cursor.fetchone()
    if not active:
        conn.close()
        return jsonify({"status": "error", "message": "No active scenario found to save notes for."}), 400
        
    cursor.execute("UPDATE user_scenarios SET notes=? WHERE id=?", (notes, active["id"]))
    conn.commit()
    conn.close()
    
    return jsonify({"status": "success", "message": "Analyst notes saved successfully."})

@scenario_blueprint.route("/api/scenario/status", methods=["GET"])
def get_scenario_status():
    if not login_required():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
        
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT us.*, s.name as scenario_name, s.difficulty, s.time_limit, s.objectives, s.attack_chain
        FROM user_scenarios us
        JOIN scenarios s ON us.scenario_id = s.scenario_id
        WHERE us.username=? AND us.status IN ('STARTED', 'PAUSED')
        ORDER BY us.id DESC LIMIT 1
    """, (session["username"],))
    active = cursor.fetchone()
    
    if not active:
        conn.close()
        return jsonify({"status": "inactive"})
        
    active = dict(active)
    
    # Get steps
    cursor.execute("SELECT * FROM scenario_steps WHERE scenario_id=? ORDER BY step_number ASC", (active["scenario_id"],))
    steps = [dict(row) for row in cursor.fetchall()]
    
    # Get collected evidence
    cursor.execute("SELECT * FROM evidence_items WHERE username=? AND scenario_id=? ORDER BY step_number ASC", (session["username"], active["scenario_id"]))
    evidence = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return jsonify({
        "status": "success",
        "scenario": active,
        "steps": steps,
        "evidence": evidence
    })
