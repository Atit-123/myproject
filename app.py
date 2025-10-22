import os
import sqlite3
import uuid
import mimetypes
from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
from werkzeug.utils import secure_filename
import google.genai as genai
from google.genai import types



# --- Configuration ---
# WARNING: This API key is still hardcoded and public. 
# For production, use os.getenv("GEMINI_API_KEY")
api_key = "AIzaSyDistLgpF0uCaNkLKDqpC4Qpx3TuQFQNGg"


if not api_key:
    raise Exception("Please set GEMINI_API_KEY environment variable")

client = genai.Client(api_key=api_key)
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
            clean_photo TEXT,
            status TEXT DEFAULT 'pending',
            ai_description TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- Helper: Save binary image ---
def save_binary_file(file_name, data):
    with open(file_name, "wb") as f:
        f.write(data)
    return file_name

# --- Serve index.html ---
@app.route("/")
def serve_index():
    return render_template("index.html")

# -------------------------------------------------------------
# --- View Reports (ADDED AND CORRECTED) ---
@app.route("/reports")
def view_reports():
    """Fetches all reports to display in the reports.html template."""
    try:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row  # To access columns by name
        c = conn.cursor()
        
        # Select columns for the report table
        c.execute("SELECT name, email, town, area, state FROM posts ORDER BY id DESC")
        
        rows = c.fetchall()
        reports_data = [dict(row) for row in rows]
        
        conn.close()

        # NOTE: Assumes you have saved your template as "reports.html" inside the 'templates' folder.
        return render_template("reports.html", reports=reports_data)
        
    except Exception as e:
        return f"<h1>Error loading reports</h1><p>{str(e)}</p>", 500
# -------------------------------------------------------------

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
            # Save uploaded photo
            filename = f"{uuid.uuid4().hex}_{secure_filename(photo.filename)}"
            path = os.path.join(UPLOAD_FOLDER, filename)
            photo.save(path)

            # --- AI Text Analysis ---
            with open(path, "rb") as f:
                image_bytes = f.read()

            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[
                        types.Content(
                            role="user",
                            parts=[
                                types.Part.from_text(
                                    text="Detect if waste/garbage is present in this photo. Answer in one short line waste_detected or waste_not_detected."
                                ),
                                types.Part.from_bytes(data=image_bytes, mime_type=photo.mimetype),
                            ],
                        )
                    ],
                )
                ai_description = getattr(response, "text", "No description")
            except Exception as e:
                print("AI analysis error:", e)
                ai_description = "AI description not available"

            # --- AI Image Generation (Clean version - CORRECTED MODEL) ---
            clean_filename = None
            try:
                generate_config = types.GenerateContentConfig(response_modalities=["IMAGE"])
                gen_response = client.models.generate_content(
                    # FIX: Corrected model name from "gemini-2.5-flash-image" to "gemini-2.5-flash"
                    model="gemini-2.5-flash",
                    contents=[
                        types.Content(
                            role="user",
                            parts=[
                                types.Part.from_text(
                                    text="Create a clean version of this place without any garbage."
                                ),
                                types.Part.from_bytes(data=image_bytes, mime_type=photo.mimetype),
                            ],
                        ),
                    ],
                    config=generate_config,
                )

                part = gen_response.candidates[0].content.parts[0]
                if getattr(part, "inline_data", None) and part.inline_data.data:
                    clean_filename = f"clean_{uuid.uuid4().hex}.png"
                    clean_path = os.path.join(UPLOAD_FOLDER, clean_filename)
                    save_binary_file(clean_path, part.inline_data.data)

            except Exception as e:
                print("AI image gen error:", e)

            # --- Save to Database ---
            conn = sqlite3.connect(DATABASE)
            c = conn.cursor()
            c.execute('''
                INSERT INTO posts(name,email,caption,town,area,state,lat,lon,photo,clean_photo,status,ai_description)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (name, email, caption, town, area, state, lat, lon, filename, clean_filename, "pending", ai_description))
            conn.commit()
            conn.close()

            results.append({
                "filename": filename,
                "ai_description": ai_description,
                "clean_photo": clean_filename
            })

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
                post["photo_url"] = "/uploads/" + post["photo"]
            else:
                post["photo_url"] = None
            if post.get("clean_photo"):
                post["clean_photo_url"] = "/uploads/" + post["clean_photo"]
            else:
                post["clean_photo_url"] = None
            posts.append(post)
        return jsonify(posts)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- Update status ---
@app.route("/update_status/<int:id>", methods=["POST"])
def update_status(id):
    data = request.get_json()
    status = data.get("status", "pending")
    if status not in ["pending", "in progress", "complete"]:
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
        c.execute("SELECT photo, clean_photo FROM posts WHERE id=?", (id,))
        row = c.fetchone()
        if row:
            for file in row:
                if file:
                    path = os.path.join(UPLOAD_FOLDER, file)
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



