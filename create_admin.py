import sqlite3
from flask_bcrypt import Bcrypt

bcrypt = Bcrypt()

conn = sqlite3.connect("database.db")
c = conn.cursor()

admin_email = "admin@garuda.com"
admin_password = "admin123"

hashed_pw = bcrypt.generate_password_hash(admin_password).decode("utf-8")

try:
    c.execute("""
        INSERT INTO users (email, password, role, status)
        VALUES (?, ?, 'admin', 'approved')
    """, (admin_email, hashed_pw))

    conn.commit()
    print("✅ Admin Created Successfully!")

except:
    print("⚠️ Admin Already Exists!")

conn.close()
