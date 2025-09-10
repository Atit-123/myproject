import os
import sqlite3
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
import google.generativeai as genai

# --- Configuration ---

# Hardcoded API key fallback - for testing only (replace with your own key or use env variable)
api_key = os.getenv("GOOGLE_GENAI_API_KEY", "AIzaSyCeQxTrf6cShJOdHkAuwufCow4sb3Bg8u4")
if not api_key:
    raise Exception("Please set the GOOGLE_GENAI_API_KEY environment variable")

genai.configure(api_key=api_key)

model = genai.GenerativeModel("gemini-1.5-flash")
UPLOAD_FOLDER = "uploads"
DATABASE = "geoclean.db"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- Initialize Flask app ---
app = Flask(__name__)
CORS(app, supports_credentials=True, methods=["GET", "POST", "DELETE"])

# --- Initialize DB ---
def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS posts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            caption TEXT,
            town TEXT,
            area TEXT,
            state TEXT,
            lat REAL,
            lon REAL,
            photo TEXT,
            status TEXT DEFAULT 'pending',
            ai_description TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- Upload endpoint ---
@app.route("/upload", methods=["POST"])
def upload_file():
    try:
        name = request.form.get("name")
        email = request.form.get("email")
        caption = request.form.get("caption")
        town = request.form.get("town")
        area = request.form.get("area")
        state = request.form.get("state")
        lat = float(request.form.get("lat", 0))
        lon = float(request.form.get("lon", 0))

        photos = request.files.getlist("photos")
        results = []

        for photo in photos:
            filename = secure_filename(photo.filename)
            path = os.path.join(UPLOAD_FOLDER, filename)
            photo.save(path)

            # --- AI Image Analysis ---
            try:
                with open(path, "rb") as f:
                    image_bytes = f.read()

                # Gemini 2 expects prompt + image input as a dict
                response = model.generate_content([
                    "Waste is detect or not detected (ex in the image there is no any waste is detected)in one line.",
                    {
                        "mime_type": "image/jpeg",
                        "data": image_bytes
                    }
                ])

                ai_description = response.text.strip()
            except Exception as e:
                print("AI error:", e)
                ai_description = "AI description not available"

            # --- Save to Database ---
            conn = sqlite3.connect(DATABASE)
            c = conn.cursor()
            c.execute('''
                INSERT INTO posts(name,email,caption,town,area,state,lat,lon,photo,status,ai_description)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ''', (name, email, caption, town, area, state, lat, lon, filename, "pending", ai_description))
            conn.commit()
            conn.close()

            results.append({"filename": filename, "ai_description": ai_description})

        return jsonify({"message": "Upload successful!", "results": results})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- Get posts ---
@app.route("/posts", methods=["GET"])
def get_posts():
    try:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM posts ORDER BY id DESC")
        rows = c.fetchall()
        conn.close()

        posts = []
        for row in rows:
            post = dict(row)
            if post.get("photo"):
                post["photo_url"] = request.host_url.rstrip("/") + "/uploads/" + post["photo"]
            else:
                post["photo_url"] = None
            posts.append(post)
        return jsonify(posts)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- Update status ---
@app.route("/update_status/<int:id>", methods=["POST"])
def update_status(id):
    data = request.get_json()
    status = data.get("status", "pending")
    if status not in ["pending", "complete"]:
        status = "pending"
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("UPDATE posts SET status=? WHERE id=?", (status, id))
        conn.commit()
        conn.close()
        return jsonify({"message": f"Status updated to {status}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- Delete post ---
@app.route("/delete_post/<int:id>", methods=["DELETE"])
def delete_post(id):
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("SELECT photo FROM posts WHERE id=?", (id,))
        row = c.fetchone()
        if row and row[0]:
            path = os.path.join(UPLOAD_FOLDER, row[0])
            if os.path.exists(path):
                os.remove(path)
        c.execute("DELETE FROM posts WHERE id=?", (id,))
        conn.commit()
        conn.close()
        return jsonify({"message": "Post deleted successfully."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- Serve uploaded images ---
@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

if __name__ == "__main__":
    app.run(debug=True)
