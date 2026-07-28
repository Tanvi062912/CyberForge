from flask import Blueprint, render_template, jsonify, session, redirect, request, send_file
import sqlite3
import os
import json
import datetime
from database import get_db

report_center_blueprint = Blueprint('report_center', __name__)

REPORT_FOLDER = "reports"
os.makedirs(REPORT_FOLDER, exist_ok=True)

def login_required():
    return "username" in session

# ---------------- REPORT COMPILING UTILITIES ----------------

def compile_incident_data(username):
    conn = get_db()
    cursor = conn.cursor()
    
    # Get active/completed user scenarios
    cursor.execute("""
        SELECT us.*, s.name as scenario_name, s.objectives, s.attack_chain, s.expected_findings 
        FROM user_scenarios us
        JOIN scenarios s ON us.scenario_id = s.scenario_id
        WHERE us.username=?
        ORDER BY us.id DESC LIMIT 1
    """, (username,))
    sc = cursor.fetchone()
    
    # Get evidence collected
    evidence = []
    if sc:
        cursor.execute("""
            SELECT * FROM evidence_items 
            WHERE username=? AND scenario_id=? 
            ORDER BY step_number ASC
        """, (username, sc["scenario_id"]))
        evidence = [dict(row) for row in cursor.fetchall()]
        sc = dict(sc)
        
    conn.close()
    
    # Return compiled structure
    return {
        "title": sc["scenario_name"] if sc else "General Incident Report",
        "objectives": sc["objectives"] if sc else "Analyze cyber range security anomalies.",
        "attack_chain": sc["attack_chain"] if sc else "N/A",
        "expected_findings": sc["expected_findings"] if sc else "N/A",
        "current_step": sc["current_step"] if sc else 0,
        "status": sc["status"] if sc else "INACTIVE",
        "started_at": sc["started_at"] if sc else "N/A",
        "notes": sc["notes"] if sc else "No analyst notes provided.",
        "evidence": evidence
    }

def compile_investigation_data(username):
    conn = get_db()
    cursor = conn.cursor()
    
    # Get user's collected evidence items
    cursor.execute("""
        SELECT ei.*, s.name as scenario_name 
        FROM evidence_items ei
        JOIN scenarios s ON ei.scenario_id = s.scenario_id
        WHERE ei.username=?
        ORDER BY ei.collected_at DESC
    """, (username,))
    evidence = [dict(row) for row in cursor.fetchall()]
    
    # Get active notes
    cursor.execute("SELECT notes, scenario_id FROM user_scenarios WHERE username=? AND status='STARTED' LIMIT 1", (username,))
    active_sc = cursor.fetchone()
    notes = active_sc["notes"] if active_sc else "No active notes."
    
    conn.close()
    
    return {
        "notes": notes,
        "evidence": evidence
    }

def compile_performance_data(username):
    conn = get_db()
    cursor = conn.cursor()
    
    # Fetch gamification user_xp stats
    cursor.execute("SELECT * FROM user_xp WHERE username=?", (username,))
    uxp = cursor.fetchone()
    if uxp:
        uxp = dict(uxp)
    else:
        uxp = {"xp": 0, "points": 0, "skill_level": "Beginner Analyst", "completed_labs": 0, "incorrect_findings": 0, "missed_evidence": 0}
        
    # Get user badges
    cursor.execute("""
        SELECT b.name, b.description 
        FROM user_badges ub
        JOIN badges b ON ub.badge_id = b.badge_id
        WHERE ub.username=?
    """, (username,))
    badges = [dict(row) for row in cursor.fetchall()]
    
    # Get list of completed academy labs
    cursor.execute("""
        SELECT al.title, lp.flag 
        FROM lab_progress lp
        JOIN academy_lessons al ON lp.lab_id = al.id
        WHERE lp.username=? AND lp.completed=1
    """, (username,))
    labs = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    total = uxp["completed_labs"] + uxp["incorrect_findings"] + uxp["missed_evidence"]
    accuracy = 100.0
    if total > 0:
        accuracy = round((uxp["completed_labs"] / total) * 100.0, 1)
        
    return {
        "xp": uxp["xp"],
        "points": uxp["points"],
        "skill_level": uxp["skill_level"],
        "completed_labs_count": uxp["completed_labs"],
        "accuracy": accuracy,
        "badges": badges,
        "completed_labs": labs
    }

# ---------------- PDF / HTML GENERATION WRAPPERS ----------------

def generate_pdf_report(title, report_type, data, filename):
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    
    doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=22,
        textColor=colors.HexColor('#00ff99'),
        spaceAfter=15
    )
    
    h2_style = ParagraphStyle(
        'H2Style',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=14,
        textColor=colors.HexColor('#a855f7'),
        spaceBefore=12,
        spaceAfter=6
    )
    
    body_style = ParagraphStyle(
        'BodyStyle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10.5,
        textColor=colors.HexColor('#1f2937'),
        spaceAfter=8
    )
    
    # Document header
    story.append(Paragraph("CYBERFORGE SECURITY OPERATIONS CENTER", ParagraphStyle('Sub', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#9ca3af'), spaceAfter=5)))
    story.append(Paragraph(title, title_style))
    story.append(Paragraph(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ParagraphStyle('Date', parent=styles['Normal'], fontSize=9, spaceAfter=20)))
    story.append(Spacer(1, 10))
    
    if report_type == "incident":
        story.append(Paragraph("Executive Summary", h2_style))
        story.append(Paragraph(f"This incident response document outlines the investigations, timeline logging, and findings for the range scenario: {data['title']}.", body_style))
        
        story.append(Paragraph("Scenario Parameters", h2_style))
        story.append(Paragraph(f"<b>Objectives:</b> {data['objectives']}", body_style))
        story.append(Paragraph(f"<b>Attack Vector Chain:</b> {data['attack_chain']}", body_style))
        story.append(Paragraph(f"<b>Expected findings indicators:</b> {data['expected_findings']}", body_style))
        story.append(Paragraph(f"<b>Status:</b> {data['status']}", body_style))
        
        story.append(Paragraph("Analyst Investigation Notes", h2_style))
        story.append(Paragraph(data['notes'], body_style))
        
        story.append(Paragraph("Collected Evidence Log", h2_style))
        if not data["evidence"]:
            story.append(Paragraph("No evidence records collected yet.", body_style))
        else:
            for ev in data["evidence"]:
                story.append(Paragraph(f"<b>Step {ev['step_number']}: {ev['title']}</b>", ParagraphStyle('EvTitle', parent=body_style, fontName='Helvetica-Bold')))
                story.append(Paragraph(ev['description'], body_style))
                story.append(Spacer(1, 4))
                
    elif report_type == "investigation":
        story.append(Paragraph("Analyst Forensic Notes", h2_style))
        story.append(Paragraph(data['notes'], body_style))
        
        story.append(Paragraph("Collected Evidence Cabinet", h2_style))
        if not data["evidence"]:
            story.append(Paragraph("No forensic evidence items collected in cabinet.", body_style))
        else:
            for ev in data["evidence"]:
                story.append(Paragraph(f"<b>{ev['scenario_name']} - Step {ev['step_number']}: {ev['title']}</b>", ParagraphStyle('EvTitle', parent=body_style, fontName='Helvetica-Bold')))
                story.append(Paragraph(ev['description'], body_style))
                story.append(Paragraph(f"<font color='#9ca3af'>Collected At: {ev['collected_at']}</font>", ParagraphStyle('Sub', parent=body_style, fontSize=8)))
                story.append(Spacer(1, 8))
                
    elif report_type == "performance":
        story.append(Paragraph("Operator Profile Summary", h2_style))
        story.append(Paragraph(f"<b>Skill Level Classification:</b> {data['skill_level']}", body_style))
        story.append(Paragraph(f"<b>Total XP Accumulated:</b> {data['xp']} XP", body_style))
        story.append(Paragraph(f"<b>Points Balance:</b> {data['points']} Points", body_style))
        story.append(Paragraph(f"<b>Submission Accuracy:</b> {data['accuracy']}%", body_style))
        story.append(Paragraph(f"<b>Total Academy Labs Completed:</b> {data['completed_labs_count']} Labs", body_style))
        
        story.append(Paragraph("Earned Badges Portfolio", h2_style))
        if not data["badges"]:
            story.append(Paragraph("No profile badges unlocked yet.", body_style))
        else:
            for b in data["badges"]:
                story.append(Paragraph(f"<b>Badge: {b['name']}</b> - {b['description']}", body_style))
                
        story.append(Paragraph("Completed Academy Lessons Progress", h2_style))
        if not data["completed_labs"]:
            story.append(Paragraph("No academy lessons completed.", body_style))
        else:
            for l in data["completed_labs"]:
                story.append(Paragraph(f"<b>{l['title']}</b> - Flag captured: <font color='#00cc77'>{l['flag']}</font>", body_style))
                
    doc.build(story)

def generate_html_report(title, report_type, data, filename):
    body_content = ""
    
    if report_type == "incident":
        body_content = f"""
        <h2>Executive Summary</h2>
        <p>This incident response document outlines the investigations, timeline logging, and findings for the range scenario: {data['title']}.</p>
        
        <h2>Scenario Parameters</h2>
        <p><strong>Objectives:</strong> {data['objectives']}</p>
        <p><strong>Attack Vector Chain:</strong> {data['attack_chain']}</p>
        <p><strong>Expected findings indicators:</strong> {data['expected_findings']}</p>
        <p><strong>Status:</strong> {data['status']}</p>
        
        <h2>Analyst Investigation Notes</h2>
        <p>{data['notes']}</p>
        
        <h2>Collected Evidence Log</h2>
        <ul>
            {"".join(f"<li><strong>Step {ev['step_number']}: {ev['title']}</strong><br>{ev['description']}</li>" for ev in data['evidence']) if data['evidence'] else "<li>No evidence collected.</li>"}
        </ul>
        """
    elif report_type == "investigation":
        body_content = f"""
        <h2>Analyst Forensic Notes</h2>
        <p>{data['notes']}</p>
        
        <h2>Collected Evidence Cabinet</h2>
        <ul>
            {"".join(f"<li><strong>{ev['scenario_name']} (Step {ev['step_number']}): {ev['title']}</strong><br>{ev['description']}<br><small style='color:#9ca3af;'>{ev['collected_at']}</small></li>" for ev in data['evidence']) if data['evidence'] else "<li>No evidence items collected.</li>"}
        </ul>
        """
    elif report_type == "performance":
        body_content = f"""
        <h2>Operator Profile Summary</h2>
        <p><strong>Skill Level Classification:</strong> {data['skill_level']}</p>
        <p><strong>Total XP Accumulated:</strong> {data['xp']} XP</p>
        <p><strong>Points Balance:</strong> {data['points']} Points</p>
        <p><strong>Submission Accuracy:</strong> {data['accuracy']}%</p>
        
        <h2>Earned Badges Portfolio</h2>
        <ul>
            {"".join(f"<li><strong>{b['name']}</strong>: {b['description']}</li>" for b in data['badges']) if data['badges'] else "<li>No badges unlocked.</li>"}
        </ul>
        
        <h2>Completed Academy Lessons Progress</h2>
        <ul>
            {"".join(f"<li><strong>{l['title']}</strong> - Flag: <code style='color:#00ff99;'>{l['flag']}</code></li>" for l in data['completed_labs']) if data['completed_labs'] else "<li>No academy lessons completed.</li>"}
        </ul>
        """
        
    html = f"""<!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>CyberForge Generated Report</title>
        <style>
            body {{ background:#050814; color:#f3f4f6; font-family:sans-serif; padding:40px; line-height:1.6; }}
            .container {{ max-width:800px; margin:0 auto; background:#0b0f19; border:1px solid #1f2937; padding:30px; border-radius:8px; }}
            h1 {{ color:#00ff99; border-bottom:1px solid #1f2937; padding-bottom:10px; }}
            h2 {{ color:#a855f7; margin-top:20px; border-bottom:1px dashed #1f2937; padding-bottom:5px; }}
            li {{ margin-bottom:15px; }}
            small {{ font-size:11px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>{title}</h1>
            <p><small>Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small></p>
            {body_content}
        </div>
    </body>
    </html>"""
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)

# ---------------- BLUEPRINT ENDPOINTS ----------------

@report_center_blueprint.route("/report_center")
def index():
    if not login_required():
        return redirect("/login")
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM generated_reports WHERE username=? ORDER BY id DESC", (session["username"],))
    reports = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return render_template(
        "report_center.html",
        username=session["username"],
        reports=reports
    )

@report_center_blueprint.route("/api/report_center/generate", methods=["POST"])
def generate_report():
    if not login_required():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
        
    data = request.get_json() or {}
    report_type = data.get("report_type") # incident, investigation, performance
    fmt = data.get("format") # pdf, html, json
    title = data.get("title", "").strip()
    
    if not report_type or not fmt or not title:
        return jsonify({"status": "error", "message": "Report Type, Format, and Title are required"}), 400
        
    # Compile relevant data
    compiled_data = {}
    if report_type == "incident":
        compiled_data = compile_incident_data(session["username"])
    elif report_type == "investigation":
        compiled_data = compile_investigation_data(session["username"])
    elif report_type == "performance":
        compiled_data = compile_performance_data(session["username"])
    else:
        return jsonify({"status": "error", "message": "Invalid report type"}), 400
        
    # Save file
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"report_{report_type}_{timestamp}.{fmt}"
    file_path = os.path.join(REPORT_FOLDER, filename)
    
    if fmt == "pdf":
        generate_pdf_report(title, report_type, compiled_data, file_path)
    elif fmt == "html":
        generate_html_report(title, report_type, compiled_data, file_path)
    elif fmt == "json":
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(compiled_data, f, indent=4)
    else:
        return jsonify({"status": "error", "message": "Invalid format requested"}), 400
        
    # Insert metadata in DB
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO generated_reports (username, title, report_type, format, file_path)
        VALUES (?, ?, ?, ?, ?)
    """, (session["username"], title, report_type, fmt, file_path))
    conn.commit()
    conn.close()
    
    # Award gamification XP for generating report
    try:
        from modules.gamification import award_xp
        award_xp(session["username"], 15, 15, f"Generated and compiled a security {report_type} report ({fmt.upper()})")
    except Exception as e:
        print(f"Error awarding gamification XP: {e}")
        
    return jsonify({"status": "success", "message": f"{report_type.capitalize()} report generated successfully in {fmt.upper()}!"})

@report_center_blueprint.route("/api/report_center/download/<int:id>")
def download_report(id):
    if not login_required():
        return redirect("/login")
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM generated_reports WHERE id=?", (id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return render_template("404.html"), 404
        
    file_path = row["file_path"]
    if not os.path.exists(file_path):
        return render_template("404.html"), 404
        
    return send_file(file_path, as_attachment=True, download_name=os.path.basename(file_path))

@report_center_blueprint.route("/api/report_center/delete/<int:id>", methods=["POST"])
def delete_report(id):
    if not login_required():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM generated_reports WHERE id=? AND username=?", (id, session["username"]))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return jsonify({"status": "error", "message": "Report not found"}), 404
        
    # Delete file if exists
    try:
        if os.path.exists(row["file_path"]):
            os.remove(row["file_path"])
    except Exception as e:
        print(f"Error deleting file: {e}")
        
    cursor.execute("DELETE FROM generated_reports WHERE id=?", (id,))
    conn.commit()
    conn.close()
    
    return jsonify({"status": "success", "message": "Report deleted successfully."})
