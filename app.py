from flask import Flask, render_template, Response, request, jsonify, redirect, url_for, flash, session, abort
import cv2
import os
import time
import smtplib
import atexit
import urllib.request   
import numpy as np
from email.message import EmailMessage
from dotenv import load_dotenv
from twilio.rest import Client
from openai import OpenAI
import subprocess
import json
from flask import send_file
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
import sqlite3
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import openpyxl
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image,
    Table, TableStyle
)
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import inch
import shutil
import threading
from datetime import datetime, timedelta
import re
import sqlite3


# Load environment variables from .env
load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "garuda_secret_key_secure_123") # Default if not in .env

# =========================
# GLOBAL MAPPING STATUS
# =========================
MAPPING_STATUS = {
    "running": False,
    "completed": False,
    "volume": None,
    "map_image": None,
    "geo_image": None
}

# Security Setup
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

DB_NAME = "database.db"
LOG_FILE = os.path.join("logs", "user_login_details.xlsx")

# Ensure logs dir exists
os.makedirs("logs", exist_ok=True)

# Initialize Excel Log if not exists
if not os.path.exists(LOG_FILE):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["User Email", "Login Date", "Login Time", "Role", "Approval Status"])
    wb.save(LOG_FILE)

# =========================
# USER MODEL & DATABASE
# =========================
class User(UserMixin):
    def __init__(self, id, email, role, status):
        self.id = id
        self.email = email
        self.role = role
        self.status = status

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    if user:
        return User(id=user[0], email=user[1], role=user[3], status=user[4])
    return None

def log_login_attempt(email, role, status):
    try:
        wb = openpyxl.load_workbook(LOG_FILE)
        ws = wb.active
        now = datetime.now()
        ws.append([
            email, 
            now.strftime("%Y-%m-%d"), 
            now.strftime("%H:%M:%S"), 
            role, 
            status
        ])
        wb.save(LOG_FILE)
    except Exception as e:
        print(f"Error logging to Excel: {e}")

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'user',
        status TEXT DEFAULT 'pending'
    )
    """)

    conn.commit()
    conn.close()

  # =========================
# NOTIFICATION FUNCTIONS
# =========================

# =========================
# EMAIL FUNCTION
# =========================
def send_confirmation_email(message, user_email, pdf_path=None):
    try:
        EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
        EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

        if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
            print("Email credentials not found in .env file")
            return False

        msg = EmailMessage()
        msg["Subject"] = "✅ Drone Survey Request Received"
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = user_email

        msg.set_content(f"""
Hello,

Your Drone Survey Request has been received successfully.

Request Details:
-------------------------
{message}


Thank you,
Drone Mining Monitoring System
""")
        # ✅ Attach PDF Report
        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                msg.add_attachment(
                    f.read(),
                    maintype="application",
                    subtype="pdf",
                    filename="Mining_Report.pdf"
                )   

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)

        print("Email Sent To:", user_email)
        return True
    except Exception as e:
        print(f"Email Error: {e}")
        return False

# =========================
# WHATSAPP FUNCTION
# =========================
# =========================
# WHATSAPP FUNCTION (FIXED)
# =========================
def send_whatsapp_message_with_pdf(message, phone_number, pdf_url):
    try:
        TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
        TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
        TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_NUMBER")

        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        # Normalize phone number
        if not phone_number.startswith("+"):
            phone_number = "+91" + phone_number

        to_number = "whatsapp:" + phone_number

        # ✅ Proper WhatsApp Formatted Text
        whatsapp_text = (
            "📌 Drone Survey Request Received\n\n"
            "Hello,\n\n"
            "Your Drone Survey Request has been received successfully.\n\n"
            "Request Details:\n"
            "-------------------------\n"
            f"{message}\n\n"
            "We will process the drone mapping soon.\n\n"
            "📄 Your PDF Report is attached above.\n\n"
            "Thank you,\n"
            "Drone Mining Monitoring System"
        )

        # ✅ Send Message + PDF Together
        msg = client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=to_number,
            body=whatsapp_text,
            media_url=[pdf_url]   # ✅ PDF Attachment
        )

        print("✅ WhatsApp Text + PDF Sent Successfully:", msg.sid)
        return True

    except Exception as e:
        print("❌ WhatsApp Send Error:", e)
        return False


def send_whatsapp_pdf(phone_number, pdf_url):
    try:
        TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
        TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
        TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_NUMBER")

        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        # Normalize phone number
        if not phone_number.startswith("+"):
            phone_number = "+91" + phone_number

        to_number = "whatsapp:" + phone_number

        msg = client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=to_number,
            body="📄 Your Drone Mining Survey Report PDF is ready!",
            media_url=[pdf_url]  # ✅ Attach PDF
        )

        print("✅ WhatsApp PDF Sent Successfully:", msg.sid)
        return True

    except Exception as e:
        print("❌ WhatsApp PDF Send Error:", e)
        return False

# =========================
# EXISTING DRONE LOGIC
# =========================
SHOT_URL = "http://10.75.165.104:8080/shot.jpg"
today = datetime.now().strftime("%Y-%m-%d")
BASE_DIR = os.path.join("storage", today)
IMG_DIR = os.path.join(BASE_DIR, "images")
VID_DIR = os.path.join(BASE_DIR, "videos")
REQ_DIR = os.path.join(BASE_DIR, "requests")

os.makedirs(IMG_DIR, exist_ok=True)
os.makedirs(VID_DIR, exist_ok=True)
os.makedirs(REQ_DIR, exist_ok=True)

def run_odm_mapping(date_folder):

    storage_path = r"D:/drone/storage"

    # ODM dataset = date folder
    dataset_name = date_folder

    cmd = f'''
    docker run --rm ^
      -v "{storage_path}":/datasets ^
      opendronemap/odm ^
      --project-path /datasets ^
      --fast-orthophoto ^
      --resize-to 1200 ^
      --matcher-neighbors 4 ^
      {date_folder}
    '''

    print("🚀 Running ODM Mapping for:", dataset_name)

    subprocess.run(cmd, shell=True)

    # Output will be generated here:
    output_folder = os.path.join(storage_path, dataset_name)

    return output_folder


def run_odm_mapping_background(date_folder, user_email):
    global MAPPING_STATUS

    try:
        MAPPING_STATUS["running"] = True
        MAPPING_STATUS["completed"] = False

        print("🚀 ODM Mapping Started for:", date_folder)

        # ✅ Run ODM for specific date folder
        output_path = run_odm_mapping(date_folder)

        # ✅ Extract Volume
        volume = extract_volume(output_path)

        # ✅ Generate PDF
        pdf_path = generate_pdf_report(volume)

        # ✅ Save Orthophoto into static folder
        ortho_src = os.path.join(output_path, "odm_orthophoto", "odm_orthophoto.png")
        ortho_dest = os.path.join("static", "mapping.png")

        if os.path.exists(ortho_src):
            shutil.copy(ortho_src, ortho_dest)

        # ✅ Store Results
        MAPPING_STATUS["volume"] = volume
        MAPPING_STATUS["map_image"] = "/static/mapping.png"
        MAPPING_STATUS["geo_image"] = "/static/geo_latest.jpg"

        # ✅ Send Email to user
        send_confirmation_email(
            f"Final Volume: {volume} m³",
            user_email,
            pdf_path
        )

        MAPPING_STATUS["completed"] = True
        MAPPING_STATUS["running"] = False

        print("✅ Mapping Completed Successfully!")

    except Exception as e:
        print("❌ Mapping Error:", e)

        MAPPING_STATUS["running"] = False
        MAPPING_STATUS["completed"] = False



def save_mapping_output(output_path):
    ortho_file = os.path.join(
        output_path,
        "odm_orthophoto",
        "odm_orthophoto.png"
    )

    if os.path.exists(ortho_file):
        static_map = os.path.join("static", "mapping.png")
        shutil.copy(ortho_file, static_map)
        return "/static/mapping.png"

    return None


def extract_volume(output_path):
    stats_file = os.path.join(output_path, "odm_report", "stats.json")

    if not os.path.exists(stats_file):
        return "⚠️ Volume file not generated yet"

    with open(stats_file) as f:
        data = json.load(f)

    # Try multiple keys ODM may store
    if "volume" in data:
        return data["volume"]

    if "area" in data:
        area = data["area"]
        avg_height = 5   # Demo assumption
        volume = area * avg_height
        return round(volume, 2)

    return "❌ Volume Not Available"


def generate_pdf_report(volume_value):

    pdf_path = os.path.join(BASE_DIR, "volume_report.pdf")

    doc = SimpleDocTemplate(pdf_path, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    # ✅ Logo
    logo_path = "static/logo.png"
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=2*inch, height=1*inch)
        story.append(logo)

    story.append(Spacer(1, 15))

    # ✅ Title
    story.append(Paragraph("Drone Mining Survey Report", styles["Title"]))
    story.append(Spacer(1, 20))

    # ✅ Basic Info
    story.append(Paragraph(f"📅 Date: {today}", styles["Normal"]))
    story.append(Paragraph("🏢 Company: Garuda Aerospace Pvt Ltd", styles["Normal"]))
    story.append(Spacer(1, 20))

    # ✅ Table Section
    data = [
        ["Parameter", "Result"],
        ["Estimated Volume", f"{volume_value} m³"],
        ["Processing Software", "OpenDroneMap + AI"],
        ["Survey Output", "DSM + Orthophoto + Volume"]
    ]

    table = Table(data, colWidths=[200, 250])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("GRID", (0,0), (-1,-1), 1, colors.black),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold")
    ]))

    story.append(table)
    story.append(Spacer(1, 25))

    # ✅ Summary Paragraph
    story.append(Paragraph("📝 Report Summary:", styles["Heading2"]))
    story.append(Paragraph(
        f"""
        This mining volume report was generated automatically using drone imagery
        and AI-powered 3D mapping. The estimated stockpile volume is
        <b>{volume_value} cubic meters</b>.
        """,
        styles["Normal"]
    ))

    story.append(Spacer(1, 30))

    # ✅ Footer
    story.append(Paragraph(
        "Generated by Garuda Aerospace AI Drone Monitoring System",
        styles["Italic"]
    ))

    doc.build(story)

    return pdf_path

fourcc = cv2.VideoWriter_fourcc(*'XVID')
video_writer = None
last_image_time = 0
CAPTURE_INTERVAL = 2  # seconds
img_counter = 0

def generate_frames():
    global video_writer, last_image_time, img_counter
    while True:
        try:
            img_resp = urllib.request.urlopen(SHOT_URL, timeout=5)
            img_np = np.array(bytearray(img_resp.read()), dtype=np.uint8)
            frame = cv2.imdecode(img_np, cv2.IMREAD_COLOR)
            if frame is None: continue
        except Exception as e:
            time.sleep(1)
            continue

        current_time = time.time()
        if video_writer is None:
            h, w, _ = frame.shape
            video_filename = datetime.now().strftime("%Y%m%d_%H%M%S") + ".avi"
            video_path = os.path.join(VID_DIR, video_filename)
            video_writer = cv2.VideoWriter(video_path, fourcc, 20.0, (w, h))
            print("New Video Started:", video_filename)

        video_writer.write(frame)

        if current_time - last_image_time >= CAPTURE_INTERVAL:
            img_counter += 1
            img_name = datetime.now().strftime("%Y%m%d_%H%M%S")
            img_file = f"{img_name}_{img_counter:03d}.jpg"
            cv2.imwrite(os.path.join(IMG_DIR, img_file), frame)
            latest_geo = os.path.join("static", "geo_latest.jpg")
            cv2.imwrite(latest_geo, frame)

            last_image_time = current_time

        ret, buffer = cv2.imencode(".jpg", frame)
        frame_bytes = buffer.tobytes()
        yield (b"--frame\r\n" b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n")

def get_mapping_preview(output_path):
    ortho_png = os.path.join(
        output_path,
        "odm_orthophoto",
        "odm_orthophoto.png"
    )

    if os.path.exists(ortho_png):
        static_path = os.path.join("static", "mapping.png")
        shutil.copy(ortho_png, static_path)
        return "/static/mapping.png"

    return None

def cleanup():
    global video_writer
    if video_writer is not None:
        video_writer.release()

atexit.register(cleanup)

def get_statistics():
    try:
        image_count = 0
        if os.path.exists(IMG_DIR):
            image_count = len([f for f in os.listdir(IMG_DIR) if f.endswith(('.jpg', '.png', '.jpeg'))])
        video_count = 0
        if os.path.exists(VID_DIR):
            video_count = len([f for f in os.listdir(VID_DIR) if f.endswith(('.avi', '.mp4', '.mov'))])
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(BASE_DIR):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.exists(fp): total_size += os.path.getsize(fp)
        storage_used_mb = total_size / (1024 * 1024)
        return {"images": image_count, "videos": video_count, "storage_mb": round(storage_used_mb, 2)}
    except:
        return {"images": 0, "videos": 0, "storage_mb": 0}



def detect_date_from_message(msg):
    msg = msg.lower()

    if "today" in msg:
        return datetime.now().strftime("%Y-%m-%d")

    if "yesterday" in msg:
        return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    match = re.search(r"\d{4}-\d{2}-\d{2}", msg)
    if match:
        return match.group()

    return None

# =========================
# ROUTES
# =========================


@app.route("/")
def index():
    logout_user()   # Force logout every time
    return redirect(url_for("login"))



@app.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        logout_user()

        
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email = ?", (email,))
        user_data = c.fetchone()
        conn.close()
        
        if user_data and bcrypt.check_password_hash(user_data[2], password):
            user_obj = User(id=user_data[0], email=user_data[1], role=user_data[3], status=user_data[4])
            
            if user_obj.status == 'approved':
                login_user(user_obj)
                log_login_attempt(email, user_obj.role, "Success")
                flash('Login Successful! Welcome to Garuda Aerospace.', 'success')
                if user_obj.role == 'admin':
                    return redirect(url_for('admin_dashboard'))
                return redirect(url_for('dashboard'))
            else:
                log_login_attempt(email, user_obj.role, "Pending/Rejected")
                flash('Access Request Sent to Admin. Please wait for approval.', 'info')
        else:
            log_login_attempt(email, "Unknown", "Failed")
            flash('Invalid Email or Password', 'error')
            
    return render_template('login.html')

@app.route("/register", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Passwords do not match!', 'error')
            return redirect(url_for('register'))
            
        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        
        try:
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute("INSERT INTO users (email, password, role, status) VALUES (?, ?, 'user', 'pending')", 
                      (email, hashed_pw))
            conn.commit()
            conn.close()
            flash('Access Request Sent! Please wait for Admin approval.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Email already exists.', 'error')
            
    return render_template('register.html')

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template('project.html')

@app.route("/admin")
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        flash('Unauthorized Access!', 'error')
        return redirect(url_for('dashboard'))
        
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM users")
    all_users = c.fetchall()
    
    # Stats
    pending = sum(1 for u in all_users if u[4] == 'pending')
    total = len(all_users)
    
    # Read Login Logs
    total_logins = 0
    if os.path.exists(LOG_FILE):
        wb = openpyxl.load_workbook(LOG_FILE)
        ws = wb.active
        total_logins = ws.max_row - 1 # Subtract header
    
    conn.close()
    
    return render_template('admin_dashboard.html', users=all_users, pending_count=pending, users_count=total, total_logins=total_logins)

@app.route("/admin/approve/<int:user_id>")
@login_required
def approve_user(user_id):
    if current_user.role != 'admin':
        abort(403)
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET status = 'approved' WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    flash('User Approved Successfully.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route("/admin/reject/<int:user_id>")
@login_required
def reject_user(user_id):
    if current_user.role != 'admin':
        abort(403)
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET status = 'pending' WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    flash('User Access Revoked.', 'info')
    return redirect(url_for('admin_dashboard'))

@app.route("/admin/delete/<int:user_id>")
@login_required
def delete_user(user_id):
    if current_user.role != 'admin':
        abort(403)
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    flash('User Deleted.', 'info')
    return redirect(url_for('admin_dashboard'))

@app.route("/ai_request", methods=["POST"])
@login_required
def ai_request():
    data = request.json

    message = data.get("message")
    email = data.get("email")
    phone = data.get("phone")

    # Save Request File
    filename = datetime.now().strftime("%H%M%S") + "_request.txt"
    filepath = os.path.join(REQ_DIR, filename)

    with open(filepath, "w") as f:
        f.write(f"Email: {email}\n")
        f.write(f"Phone: {phone}\n")
        f.write(f"Message: {message}\n")

    # ✅ Correct Notification Calls
    # ✅ Generate PDF Report First
    volume_value = "Pending Calculation"
    pdf_path = generate_pdf_report(volume_value)

# ✅ Send Email with PDF Attachment
    email_status = send_confirmation_email(message, email, pdf_path)

# Use your ngrok public link
    pdf_public_url = "https://drone-mining-dashboard.onrender.com/public_report"

    whatsapp_status = send_whatsapp_message_with_pdf(
    message,
    phone,
    pdf_public_url
)




    return jsonify({
        "status": "success",
        "file": filename,
        "notifications": {
            "email": email_status,
            "whatsapp": whatsapp_status
        }
    })

# =========================
# EXISTING API/VIDEO
# =========================
@app.route("/video")
def video():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    return Response(generate_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/api/statistics", methods=["GET"])
@login_required
def api_statistics():
    stats = get_statistics()
    return jsonify({"status": "success", "data": stats})

@app.route("/chat_ai", methods=["POST"])
@login_required
def chat_ai():
    global MAPPING_STATUS

    data = request.json
    user_msg = data.get("message", "").strip().lower()

    if not user_msg:
        return jsonify({"reply": "⚠️ Please type something!"})

    # ===============================
    # 1️⃣ START MAPPING COMMAND
    # ===============================
    if any(cmd in user_msg for cmd in ["generate mapping", "start mapping", "3d mapping"]):

       if not MAPPING_STATUS["running"]:

        # ✅ Detect date folder from message
        date_folder = detect_date_from_message(user_msg)

        if not date_folder:
            return jsonify({
                "reply": "⚠️ Please type date like: generate mapping 2026-02-10 or today volume"
            })

        # ✅ Get user email
        user_email = current_user.email

        # ✅ Start ODM Background Thread WITH args
        threading.Thread(
            target=run_odm_mapping_background,
            args=(date_folder, user_email)
        ).start()

        return jsonify({
            "reply": f"""
🚀 Mapping Started Successfully!

📅 Dataset Date: {date_folder}

📸 Drone images are processing...
⏳ Please wait 5–10 minutes.

Type **status** to check progress.
"""
        })


    else:
        return jsonify({
                "reply": "⏳ Mapping already running... please wait."
            })

    # ===============================
    # 2️⃣ STATUS CHECK COMMAND
    # ===============================
    if "status" in user_msg:

        if MAPPING_STATUS["completed"]:
            return jsonify({
                "reply": f"""
✅ Mapping Completed Successfully!

📊 Final Volume: {MAPPING_STATUS['volume']} m³

🗺️ 3D Mapping Output Updated
📍 Geo-tag Proof Image Updated

⬇️ Download PDF:
http://127.0.0.1:5000/download_report
""",
                "volume": MAPPING_STATUS["volume"],
                "map_image": MAPPING_STATUS["map_image"],
                "geo_image": MAPPING_STATUS["geo_image"]
            })

        elif MAPPING_STATUS["running"]:
            return jsonify({
                "reply": "⏳ Still Processing... please wait and try again."
            })

        else:
            return jsonify({
                "reply": "⚠️ No mapping started yet. Type 'generate mapping'."
            })

    # ===============================
    # 3️⃣ NORMAL AI CHAT RESPONSE
    # ===============================
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.7,
        max_tokens=500,
        messages=[
            {"role": "system", "content": "You are Garuda Aerospace AI Assistant."},
            {"role": "user", "content": user_msg}
        ]
    )

    return jsonify({"reply": response.choices[0].message.content})


@app.route("/download_report")
@login_required
def download_report():
    pdf_path = os.path.join(BASE_DIR, "volume_report.pdf") # Case sensitive fix
    if not os.path.exists(pdf_path):
        return "⚠️ Report not generated yet!"
    return send_file(pdf_path, as_attachment=True)

@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email = ? AND role='admin'", (email,))
        admin_data = c.fetchone()
        conn.close()

        if admin_data and bcrypt.check_password_hash(admin_data[2], password):
            admin_obj = User(
                id=admin_data[0],
                email=admin_data[1],
                role=admin_data[3],
                status=admin_data[4]
            )

            login_user(admin_obj)
            flash("Admin Login Successful!", "success")
            return redirect(url_for("admin_dashboard"))

        else:
            flash("Invalid Admin Credentials", "error")

    return render_template("admin_login.html")

@app.route("/report_pdf")
def report_pdf():
    pdf_path = os.path.join(BASE_DIR, "volume_report.pdf")
    return send_file(pdf_path, mimetype="application/pdf")

@app.route("/public_report")
def public_report():
    pdf_path = os.path.join(BASE_DIR, "volume_report.pdf")
    if not os.path.exists(pdf_path):
        return "Report not ready yet!"
    return send_file(pdf_path, mimetype="application/pdf")
@app.route("/setup-admin")
def setup_admin():
    hashed_pw = bcrypt.generate_password_hash("Yogesh@0901").decode("utf-8")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("""
    INSERT OR IGNORE INTO users (email, password, role, status)
    VALUES (?, ?, 'admin', 'approved')
    """, ("yogeshmalavai9@gmail.com", hashed_pw))

    conn.commit()
    conn.close()

    return "✅ Admin Created Successfully"

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
