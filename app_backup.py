from flask import Flask, render_template, Response, request, jsonify
import cv2
import os
import datetime
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


# Load environment variables from .env
load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = Flask(__name__)

# =========================
# CAMERA SOURCE
# =========================
SHOT_URL = "http://10.75.165.104:8080/shot.jpg"

# =========================
# DATE-WISE STORAGE
# =========================
today = datetime.datetime.now().strftime("%Y-%m-%d")

BASE_DIR = os.path.join("storage", today)
IMG_DIR = os.path.join(BASE_DIR, "images")
VID_DIR = os.path.join(BASE_DIR, "videos")
REQ_DIR = os.path.join(BASE_DIR, "requests")

os.makedirs(IMG_DIR, exist_ok=True)
os.makedirs(VID_DIR, exist_ok=True)
os.makedirs(REQ_DIR, exist_ok=True)

print("Saving Data Inside:", BASE_DIR)

# =========================
# ODM + REPORT AUTOMATION
# =========================

def run_odm_mapping():
    """
    Runs OpenDroneMap automatically using today's captured images
    """
    images_path = IMG_DIR
    output_path = os.path.join(BASE_DIR, "odm_output")

    os.makedirs(output_path, exist_ok=True)

    cmd = f"""
    docker run --rm -v "{os.path.abspath(images_path)}":/datasets/images \
    -v "{os.path.abspath(output_path)}":/datasets/output \
    opendronemap/odm --project-path /datasets
    """

    print("OpenDroneMap Processing Started...")
    subprocess.Popen(cmd, shell=True)

    return output_path

def extract_volume(output_path):
    """
    Extract volume from ODM stats.json
    """
    stats_file = os.path.join(output_path, "odm_report", "stats.json")

    if not os.path.exists(stats_file):
        return None

    with open(stats_file) as f:
        data = json.load(f)

    return data.get("volume", "Not Found")

def generate_pdf_report(volume_value):
    """
    Generate Volume Report PDF
    """
    pdf_path = os.path.join(BASE_DIR, "volume_report.pdf")

    doc = SimpleDocTemplate(pdf_path)
    styles = getSampleStyleSheet()

    story = []
    story.append(Paragraph("Drone Mining Volume Report", styles["Title"]))
    story.append(Paragraph(f"Date: {today}", styles["Normal"]))
    story.append(Paragraph(f"Estimated Volume: {volume_value} m³", styles["Normal"]))
    story.append(Paragraph("Generated using AI + OpenDroneMap", styles["Normal"]))
    story.append(Paragraph("Garuda Aerospace Private Limited", styles["Normal"]))

    doc.build(story)

    return pdf_path

# =========================
# VIDEO WRITER SETUP
# =========================
fourcc = cv2.VideoWriter_fourcc(*'XVID')
video_writer = None
video_filename = None

# =========================
# IMAGE CAPTURE SETTINGS
# =========================
last_image_time = 0
CAPTURE_INTERVAL = 0.25  # 4 images/sec
img_counter = 0

# =========================
# VIDEO STREAM + STORAGE
# =========================
def generate_frames():
    global video_writer, last_image_time, img_counter

    while True:
        try:
            img_resp = urllib.request.urlopen(SHOT_URL, timeout=5)
            img_np = np.array(bytearray(img_resp.read()), dtype=np.uint8)
            frame = cv2.imdecode(img_np, cv2.IMREAD_COLOR)

            if frame is None:
                continue

        except Exception as e:
            print("Camera Error:", e)
            time.sleep(1)
            continue

        current_time = time.time()

        # 🎥 Start New Video File Once
        if video_writer is None:
            h, w, _ = frame.shape
            video_filename = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".avi"
            video_path = os.path.join(VID_DIR, video_filename)

            video_writer = cv2.VideoWriter(video_path, fourcc, 20.0, (w, h))
            print("New Video Started:", video_filename)

        # 🎥 Save Video Frame
        video_writer.write(frame)

        # 🖼️ Save Images (4 per second)
        if current_time - last_image_time >= CAPTURE_INTERVAL:
            img_counter += 1
            img_name = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            img_file = f"{img_name}_{img_counter:03d}.jpg"

            cv2.imwrite(os.path.join(IMG_DIR, img_file), frame)
            last_image_time = current_time

        # 🌐 Stream to Website
        ret, buffer = cv2.imencode(".jpg", frame)
        frame_bytes = buffer.tobytes()

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + frame_bytes +
            b"\r\n"
        )

# =========================
# CLEANUP FUNCTION
# =========================
def cleanup():
    global video_writer
    if video_writer is not None:
        video_writer.release()
        print("Video file saved & closed properly")

atexit.register(cleanup)

# =========================
# STATISTICS FUNCTION
# =========================
def get_statistics():
    """Get real statistics from storage directories"""
    try:
        # Count images
        image_count = 0
        if os.path.exists(IMG_DIR):
            image_count = len([f for f in os.listdir(IMG_DIR) if f.endswith(('.jpg', '.png', '.jpeg'))])
        
        # Count videos
        video_count = 0
        if os.path.exists(VID_DIR):
            video_count = len([f for f in os.listdir(VID_DIR) if f.endswith(('.avi', '.mp4', '.mov'))])
        
        # Count requests
        request_count = 0
        if os.path.exists(REQ_DIR):
            request_count = len([f for f in os.listdir(REQ_DIR) if f.endswith('.txt')])
        
        # Calculate total storage used (in MB)
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(BASE_DIR):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.exists(fp):
                    total_size += os.path.getsize(fp)
        
        storage_used_mb = total_size / (1024 * 1024)  # Convert to MB
        storage_used_gb = storage_used_mb / 1024  # Convert to GB
        
        return {
            "images": image_count,
            "videos": video_count,
            "requests": request_count,
            "storage_mb": round(storage_used_mb, 2),
            "storage_gb": round(storage_used_gb, 2)
        }
    except Exception as e:
        print(f"Error getting statistics: {e}")
        return {
            "images": 0,
            "videos": 0,
            "requests": 0,
            "storage_mb": 0,
            "storage_gb": 0
        }

# =========================
# EMAIL FUNCTION
# =========================
def send_confirmation_email(message, user_email):
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

We will process the drone mapping soon.

Thank you,
Drone Mining Monitoring System
""")

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
def send_whatsapp_message(message, phone_number):
    try:
        # Load Twilio credentials from .env
        TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
        TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
        TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_NUMBER")

        # Check credentials
        if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_WHATSAPP_FROM:
            error_msg = f"Missing credentials - SID: {bool(TWILIO_ACCOUNT_SID)}, TOKEN: {bool(TWILIO_AUTH_TOKEN)}, FROM: {bool(TWILIO_WHATSAPP_FROM)}"
            print(f"WhatsApp credentials not found: {error_msg}")
            return False

        print(f"[DEBUG] Using Twilio SID: {TWILIO_ACCOUNT_SID[:10]}...")
        print(f"[DEBUG] From Number: {TWILIO_WHATSAPP_FROM}")

        # Initialize Twilio Client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        # Clean user entered number
        original_phone = phone_number
        phone_number = phone_number.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        
        print(f"[DEBUG] Original phone: {original_phone}")
        print(f"[DEBUG] Cleaned phone: {phone_number}")

        # Format properly for Twilio WhatsApp
        if phone_number.startswith("+"):
            to_number = "whatsapp:" + phone_number
        else:
            # Default India country code if user enters without +
            to_number = "whatsapp:+91" + phone_number

        print(f"[DEBUG] Final recipient: {to_number}")
        print(f"[DEBUG] Message length: {len(message)} chars")

        # WhatsApp Message Content
        whatsapp_message = f"""
Drone Survey Request Received

Hello,

Your Drone Survey Request has been received successfully.

Request Details:
-------------------------
{message}

We will process the drone mapping soon.

Thank you,
Drone Mining Monitoring System
"""

        # Send WhatsApp Message
        print("[DEBUG] Sending WhatsApp message via Twilio...")
        msg = client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            body=whatsapp_message,
            to=to_number
        )

        print("WhatsApp Sent Successfully To:", to_number)
        print("Message SID:", msg.sid)
        print(f"[DEBUG] Message status: {msg.status}")
        return True

    except Exception as e:
        import traceback
        print(f"WhatsApp Error: {type(e).__name__}: {e}")
        print(f"[DEBUG] Full traceback:")
        traceback.print_exc()
        return False

# =========================
# ROUTES
# =========================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/video")
def video():
    return Response(generate_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

# =========================
# STATISTICS API ROUTE
# =========================
@app.route("/api/statistics", methods=["GET"])
def api_statistics():
    """Return real-time statistics"""
    stats = get_statistics()
    return jsonify({
        "status": "success",
        "data": stats
    })

# =========================
# AI REQUEST ROUTE (CHAT BOX)
# =========================
@app.route("/ai_request", methods=["POST"])
def ai_request():
    try:
        data = request.json

        # Validate required fields
        message = data.get("message", "").strip()
        email = data.get("email", "").strip()
        phone = data.get("phone", "").strip()

        if not message or not email:
            return jsonify({
                "status": "error",
                "message": "Message and Email are required"
            }), 400

        # Basic email validation
        if "@" not in email or "." not in email:
            return jsonify({
                "status": "error",
                "message": "Invalid email format"
            }), 400

        # Save request in file
        filename = datetime.datetime.now().strftime("%H%M%S") + ".txt"

        with open(os.path.join(REQ_DIR, filename), "w") as f:
            f.write("Message: " + message + "\n")
            f.write("Email: " + email + "\n")
            f.write("Phone: " + phone + "\n")
            f.write("Timestamp: " +
                    datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")

        print("Request Saved:", filename)

        # Send Email Confirmation
        email_sent = send_confirmation_email(message, email)

        # Send WhatsApp Confirmation (if phone number provided)
        whatsapp_sent = False
        if phone:
            whatsapp_sent = send_whatsapp_message(message, phone)

        results = {
            "email": email_sent,
            "whatsapp": whatsapp_sent
        }

        # Determine response based on what was sent
        if email_sent or whatsapp_sent:
            sent_via = []
            if email_sent:
                sent_via.append("email")
            if whatsapp_sent:
                sent_via.append("WhatsApp")

            return jsonify({
                "status": "success",
                "message": f"✅ Request saved and sent via {' and '.join(sent_via)}!",
                "file": filename,
                "notifications": results
            })
        else:
            return jsonify({
                "status": "error",
                "message": "⚠️ Request saved but notification failed. Check .env settings.",
                "notifications": results
            })

    except Exception as e:
        print(f"Error in ai_request: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

# =========================
# REAL AI CHAT ROUTE (NEW)
# =========================
@app.route("/chat_ai", methods=["POST"])
def chat_ai():
    try:
        data = request.json
        user_msg = data.get("message", "").strip()

        if not user_msg:
            return jsonify({"reply": "⚠️ Please type something to ask me!"})

        # ✅ Detect Mapping Command
        if "3d" in user_msg.lower() or "mapping" in user_msg.lower():
            output_path = run_odm_mapping()

            # Wait a bit for stats.json (demo purpose)
            time.sleep(10)

            volume = extract_volume(output_path)

            if volume is None:
                volume = "Processing..."

            generate_pdf_report(volume)
            return jsonify({
                "reply": f"""
✅ OpenDroneMap Started!

📂 Images Used: {IMG_DIR}

📊 Estimated Volume: {volume}

📄 Report Generated: Mining_Report.pdf

⬇️ Download Here:
http://127.0.0.1:5000/download_report
"""
            })

        # ✅ Enhanced AI Response using GPT with better system prompt
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.7,
                max_tokens=800,
                messages=[
                    {
                        "role": "system",
                        "content": """You are Garuda Aerospace AI Assistant - an expert in drone mining, 3D mapping, and geospatial surveying. 

Your personality: Friendly, professional, and highly knowledgeable about:
- Drone mining surveys and operations
- 3D mapping and point cloud processing
- Volume estimation and mining calculations
- Geotag photography and location data
- Mining site analysis and reporting

Guidelines:
1. Be conversational and engaging like ChatGPT
2. Use clear formatting with emojis for better readability
3. Provide detailed but concise explanations
4. Ask clarifying questions if needed
5. Offer practical solutions and recommendations
6. Include relevant technical details when appropriate
7. Be helpful in both technical and non-technical contexts

When users ask about surveys, volumes, or mapping:
- Provide step-by-step explanations
- Include relevant metrics and units
- Suggest best practices
- Offer optimization tips

Remember: You're helping mining professionals make data-driven decisions.
"""
                    },
                    {"role": "user", "content": user_msg}
                ]
            )

            ai_reply = response.choices[0].message.content
            return jsonify({"reply": ai_reply})

        except Exception as api_error:
            print(f"OpenAI API Error: {api_error}")
            
            # Fallback responses when API fails
            user_msg_lower = user_msg.lower()
            
            if any(word in user_msg_lower for word in ["volume", "area", "depth", "estimate"]):
                return jsonify({
                    "reply": """📊 **Volume Calculator**

I can help you estimate volume! Here's what I need:

1️⃣ **Location/Area Name** (e.g., "Goa Mining Site")
2️⃣ **Surface Area** (in m² or hectares)
3️⃣ **Average Depth** (in meters)

**Formula**: Volume = Area × Depth

Example:
- Area: 5,000 m²
- Depth: 25 m
- **Volume = 125,000 m³ = 125 × 1000 m³**

💡 *Tip: Use drone surveys for accurate area and depth measurements!*

Would you like me to calculate something specific?"""
                })
            
            elif any(word in user_msg_lower for word in ["survey", "flight", "drone", "scan"]):
                return jsonify({
                    "reply": """🚁 **Drone Survey Guide**

Great! Here's how to plan a mining survey:

**Pre-Survey Checklist:**
✓ Check weather conditions (wind < 15 km/h)
✓ Verify battery levels (30 min flight time)
✓ Calibrate camera and sensors
✓ Set GPS and altitude limits
✓ Plan flight path for complete coverage

**Flight Parameters:**
- Altitude: 50-100m for detail
- Speed: 5-10 m/s
- Overlap: 75% for 3D reconstruction
- Real GSD: 1-2 cm per pixel

**Post-Survey:**
📸 Collect all photos
🗺️ Process point clouds
📊 Generate reports
📍 Extract geotags

Would you like more details on any step?"""
                })
            
            elif any(word in user_msg_lower for word in ["photo", "image", "geotag", "location"]):
                return jsonify({
                    "reply": """📸 **Geotag Photo Information**

Geotag photos are images with location data embedded!

**What's Included:**
📍 GPS Coordinates (Latitude, Longitude, Altitude)
🕐 Timestamp
🧭 Drone orientation & compass direction
📏 Camera settings & focal length

**Benefits:**
✓ Precise location reference
✓ 3D reconstruction accuracy
✓ Site change monitoring
✓ Legal documentation
✓ Easy GIS integration

**Our System Features:**
🖼️ Automatic geotag extraction
🗺️ Photo location overlay on maps
📊 Time-series analysis
🔗 Integration with 3D models

Need help organizing or analyzing your photos?"""
                })
            
            elif any(word in user_msg_lower for word in ["help", "how", "what", "tell"]):
                return jsonify({
                    "reply": """👋 **Welcome to Garuda Aerospace AI Assistant!**

I'm here to help you with:

🚁 **Drone Surveys** - Flight planning, best practices, optimization
🗺️ **3D Mapping** - Point clouds, mesh generation, mesh processing
📊 **Volume Analysis** - Area estimation, depth calculation, total volume
📸 **Geotag Photos** - Location extraction, photo galleries, site documentation
📈 **Mining Reports** - Data analysis, trend analysis, insights

**Try asking me about:**
- "How do I plan a drone survey?"
- "Calculate volume for area 2000m² and depth 15m"
- "Show 3D mapping for Goa"
- "How do geotag photos work?"
- "What's the best flight altitude?"

What would you like to know? 😊"""
                })
            
            else:
                return jsonify({
                    "reply": f"""🤔 **Interesting question!**

*"{ user_msg}"*

I'm currently experiencing a temporary API connection issue, but I'm still here to help! 

Here's what I can assist with:
✅ 3D Mapping & Point Cloud Processing
✅ Volume Estimation Calculations  
✅ Drone Flight Planning
✅ Geotag Photo Organization
✅ Mining Site Analysis
✅ Data Interpretation & Reports

**Try rephrasing your question with specific details:**
- Location name
- Measurements (area, depth)
- Type of survey (mapping, analysis, documentation)

I'm ready to help with more specific technical details! 🚁"""
                })

    except Exception as e:
        print(f"Unexpected AI Chat Error: {e}")
        return jsonify({
            "reply": "An unexpected error occurred. Please try again. I'm here to help with drone surveys, 3D mapping, and volume calculations!"
        })

@app.route("/download_report")
def download_report():
    pdf_path = os.path.join(BASE_DIR, "volume_Report.pdf")

    if not os.path.exists(pdf_path):
        return "⚠️ Report not generated yet!"

    return send_file(pdf_path, as_attachment=True)

# =========================
# RUN APPLICATION
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
