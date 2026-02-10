import sqlite3
from flask_bcrypt import Bcrypt
from flask import Flask

app = Flask(__name__)
bcrypt = Bcrypt(app)

DB_NAME = "database.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Create Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create Default Admin
    admin_email = "yogeshmalavai9@gmail.com"
    admin_password = "Yogesh@0901"
    hashed_password = bcrypt.generate_password_hash(admin_password).decode('utf-8')
    
    try:
        cursor.execute("INSERT INTO users (email, password, role, status) VALUES (?, ?, 'admin', 'approved')", 
                       (admin_email, hashed_password))
        print(f"Admin account created: {admin_email}")
    except sqlite3.IntegrityError:
        print("Admin account already exists.")
    
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

if __name__ == "__main__":
    init_db()
