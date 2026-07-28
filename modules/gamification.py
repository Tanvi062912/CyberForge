from flask import Blueprint, render_template, jsonify, session, redirect
import sqlite3
from database import get_db

gamification_blueprint = Blueprint('gamification', __name__)

def login_required():
    return "username" in session

def get_or_create_xp(username, cursor):
    cursor.execute("SELECT * FROM user_xp WHERE username=?", (username,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("""
            INSERT INTO user_xp (username, xp, points, skill_level, completed_labs, incorrect_findings, missed_evidence)
            VALUES (?, 0, 0, 'Beginner Analyst', 0, 0, 0)
        """, (username,))
        cursor.execute("SELECT * FROM user_xp WHERE username=?", (username,))
        row = cursor.fetchone()
    return dict(row)

def update_skill_level(xp):
    if xp < 100:
        return 'Beginner Analyst'
    elif xp < 300:
        return 'Threat Hunter'
    elif xp < 600:
        return 'SOC Defender'
    elif xp < 1000:
        return 'Incident Responder'
    else:
        return 'CyberForge Elite'

def check_and_award_badges(username, cursor):
    # Fetch user details
    cursor.execute("SELECT * FROM user_xp WHERE username=?", (username,))
    uxp = cursor.fetchone()
    if not uxp:
        return []
    
    xp = uxp["xp"]
    completed_labs = uxp["completed_labs"]
    
    earned = []
    
    # Get currently earned badges
    cursor.execute("SELECT badge_id FROM user_badges WHERE username=?", (username,))
    existing = {row["badge_id"] for row in cursor.fetchall()}
    
    # 1. Beginner Analyst
    if xp >= 50 and "beginner_analyst" not in existing:
        cursor.execute("INSERT INTO user_badges (username, badge_id) VALUES (?, 'beginner_analyst')", (username,))
        earned.append("Beginner Analyst")
        
    # 2. Threat Hunter
    if completed_labs >= 2 and "threat_hunter" not in existing:
        cursor.execute("INSERT INTO user_badges (username, badge_id) VALUES (?, 'threat_hunter')", (username,))
        earned.append("Threat Hunter")
        
    # 3. SOC Defender
    if completed_labs >= 4 and "soc_defender" not in existing:
        cursor.execute("INSERT INTO user_badges (username, badge_id) VALUES (?, 'soc_defender')", (username,))
        earned.append("SOC Defender")
        
    # 4. CyberForge Elite
    if xp >= 1000 and "cyberforge_elite" not in existing:
        cursor.execute("INSERT INTO user_badges (username, badge_id) VALUES (?, 'cyberforge_elite')", (username,))
        earned.append("CyberForge Elite")
        
    return earned

def update_leaderboard_cache():
    conn = get_db()
    cursor = conn.cursor()
    
    # Clear current leaderboard
    cursor.execute("DELETE FROM leaderboard")
    
    # Fetch all users sorted by XP DESC
    cursor.execute("SELECT * FROM user_xp ORDER BY xp DESC, username ASC")
    users = cursor.fetchall()
    
    for idx, uxp in enumerate(users):
        rank = idx + 1
        username = uxp["username"]
        xp = uxp["xp"]
        labs = uxp["completed_labs"]
        
        # Calculate accuracy percentage
        total = labs + uxp["incorrect_findings"] + uxp["missed_evidence"]
        accuracy = 100.0
        if total > 0:
            accuracy = round((labs / total) * 100.0, 1)
            
        cursor.execute("""
            INSERT OR REPLACE INTO leaderboard (username, rank, xp, completed_labs, accuracy)
            VALUES (?, ?, ?, ?, ?)
        """, (username, rank, xp, labs, accuracy))
        
    conn.commit()
    conn.close()

# Public Service APIs for other modules
def award_xp(username, points_val, xp_val, reason):
    conn = get_db()
    cursor = conn.cursor()
    
    # Ensure user has record
    uxp = get_or_create_xp(username, cursor)
    
    new_xp = uxp["xp"] + xp_val
    new_points = max(0, uxp["points"] + points_val)
    new_level = update_skill_level(new_xp)
    
    # Fetch completed labs from existing SQLite progress
    cursor.execute("SELECT COUNT(*) FROM lab_progress WHERE username=? AND completed=1", (username,))
    completed = cursor.fetchone()[0]
    
    cursor.execute("""
        UPDATE user_xp 
        SET xp=?, points=?, skill_level=?, completed_labs=?
        WHERE username=?
    """, (new_xp, new_points, new_level, completed, username))
    
    # Check for achievements
    check_and_award_badges(username, cursor)
    
    # Log activity in standard audit log
    cursor.execute("""
        INSERT INTO activity_logs (username, activity)
        VALUES (?, ?)
    """, (username, f"Earned {xp_val} XP and {points_val} Points. Reason: {reason}"))
    
    conn.commit()
    conn.close()
    update_leaderboard_cache()

def deduct_points(username, points_deduct, reason):
    conn = get_db()
    cursor = conn.cursor()
    
    uxp = get_or_create_xp(username, cursor)
    new_points = max(0, uxp["points"] - points_deduct)
    new_incorrect = uxp["incorrect_findings"] + 1
    
    cursor.execute("""
        UPDATE user_xp 
        SET points=?, incorrect_findings=?
        WHERE username=?
    """, (new_points, new_incorrect, username))
    
    cursor.execute("""
        INSERT INTO activity_logs (username, activity)
        VALUES (?, ?)
    """, (username, f"Deducted {points_deduct} Points. Reason: {reason}"))
    
    conn.commit()
    conn.close()
    update_leaderboard_cache()

@gamification_blueprint.route("/gamification")
def index():
    if not login_required():
        return redirect("/login")
        
    conn = get_db()
    cursor = conn.cursor()
    
    # Get user profile
    cursor.execute("SELECT * FROM user_xp WHERE username=?", (session["username"],))
    uxp = cursor.fetchone()
    if not uxp:
        # Create default
        get_or_create_xp(session["username"], cursor)
        conn.commit()
        cursor.execute("SELECT * FROM user_xp WHERE username=?", (session["username"],))
        uxp = cursor.fetchone()
        
    uxp = dict(uxp)
    
    # Get user badges
    cursor.execute("""
        SELECT ub.earned_at, b.name, b.description, b.icon 
        FROM user_badges ub
        JOIN badges b ON ub.badge_id = b.badge_id
        WHERE ub.username=?
        ORDER BY ub.id DESC
    """, (session["username"],))
    badges = [dict(row) for row in cursor.fetchall()]
    
    # Get leaderboard
    cursor.execute("SELECT * FROM leaderboard ORDER BY rank ASC LIMIT 10")
    leaderboard = [dict(row) for row in cursor.fetchall()]
    
    # Check if the user is in the leaderboard list, if not get user's rank
    user_rank = None
    cursor.execute("SELECT rank FROM leaderboard WHERE username=?", (session["username"],))
    rank_row = cursor.fetchone()
    if rank_row:
        user_rank = rank_row["rank"]
        
    conn.close()
    
    # Calculate accuracy
    total_acc_denom = uxp["completed_labs"] + uxp["incorrect_findings"] + uxp["missed_evidence"]
    accuracy = 100.0
    if total_acc_denom > 0:
        accuracy = round((uxp["completed_labs"] / total_acc_denom) * 100.0, 1)

    return render_template(
        "gamification.html",
        username=session["username"],
        stats=uxp,
        badges=badges,
        leaderboard=leaderboard,
        user_rank=user_rank,
        accuracy=accuracy
    )

@gamification_blueprint.route("/api/gamification/profile")
def profile():
    if not login_required():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_xp WHERE username=?", (session["username"],))
    uxp = cursor.fetchone()
    
    cursor.execute("""
        SELECT b.badge_id, b.name, b.description, b.icon 
        FROM user_badges ub
        JOIN badges b ON ub.badge_id = b.badge_id
        WHERE ub.username=?
    """, (session["username"],))
    badges = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    if not uxp:
        return jsonify({"status": "success", "xp": 0, "points": 0, "badges": []})
        
    uxp = dict(uxp)
    uxp["badges"] = badges
    return jsonify({"status": "success", "profile": uxp})
