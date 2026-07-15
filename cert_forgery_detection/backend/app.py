from flask import Flask, request, jsonify, send_from_directory, session
from flask_cors import CORS
import os, json, hashlib, secrets, re
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
FRONTEND      = os.path.join(BASE_DIR, '..', 'frontend')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
DB_FILE       = os.path.join(BASE_DIR, 'users.json')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__, static_folder=FRONTEND, static_url_path="")
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))
CORS(app, supports_credentials=True)

UPLOADER_ID       = os.getenv("UPLOADER_ID", "uploader")
UPLOADER_PASSWORD = os.getenv("UPLOADER_PASSWORD", "upload@123")

# ── DB helpers ─────────────────────────────────────────────────────────────

def load_db() -> dict:
    if not os.path.exists(DB_FILE):
        return {"verifiers": {}, "reset_tokens": {}}
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(db: dict):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)

def hash_password(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()

def save_file(file) -> str:
    path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(path)
    return path

# ── Frontend ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(FRONTEND, "index.html")

# ══════════════════════════════════════════════════════════════════════════
# AUTH — UPLOADER
# ══════════════════════════════════════════════════════════════════════════

@app.route("/api/auth/uploader/login", methods=["POST"])
def uploader_login():
    data = request.get_json()
    if (data.get("username","").strip() == UPLOADER_ID
            and data.get("password","").strip() == UPLOADER_PASSWORD):
        session["role"]     = "uploader"
        session["username"] = UPLOADER_ID
        return jsonify({"success": True, "role": "uploader"})
    return jsonify({"success": False, "error": "Invalid credentials"}), 401

@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})

# ══════════════════════════════════════════════════════════════════════════
# AUTH — VERIFIER
# ══════════════════════════════════════════════════════════════════════════

@app.route("/api/auth/verifier/register", methods=["POST"])
def verifier_register():
    data  = request.get_json()
    uid   = data.get("username","").strip()
    pwd   = data.get("password","").strip()
    email = data.get("email","").strip()
    org   = data.get("organization","").strip()
    if not uid or not pwd or not email:
        return jsonify({"success": False, "error": "All fields are required"}), 400
    if len(pwd) < 6:
        return jsonify({"success": False, "error": "Password must be at least 6 characters"}), 400
    if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        return jsonify({"success": False, "error": "Invalid email address"}), 400
    db = load_db()
    if uid in db["verifiers"]:
        return jsonify({"success": False, "error": "Username already exists"}), 400
    db["verifiers"][uid] = {
        "password":     hash_password(pwd),
        "email":        email,
        "organization": org,
        "created_at":   datetime.now().isoformat(),
    }
    save_db(db)
    return jsonify({"success": True})

@app.route("/api/auth/verifier/login", methods=["POST"])
def verifier_login():
    data = request.get_json()
    uid  = data.get("username","").strip()
    pwd  = data.get("password","").strip()
    db   = load_db()
    user = db["verifiers"].get(uid)
    if not user or user["password"] != hash_password(pwd):
        return jsonify({"success": False, "error": "Invalid credentials"}), 401
    session["role"]     = "verifier"
    session["username"] = uid
    return jsonify({"success": True, "role": "verifier", "username": uid})

@app.route("/api/auth/verifier/forgot-password", methods=["POST"])
def forgot_password():
    data  = request.get_json()
    email = data.get("email","").strip()
    db    = load_db()
    found = next((uid for uid, info in db["verifiers"].items()
                  if info["email"].lower() == email.lower()), None)
    if not found:
        return jsonify({"success": True,
                        "message": "If that email is registered, a reset token has been generated."})
    token = secrets.token_urlsafe(32)
    db["reset_tokens"][token] = {
        "username":   found,
        "expires_at": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    save_db(db)
    return jsonify({
        "success": True,
        "message": "Reset token generated.",
        "token":   token,
        "note":    "Use this token to set a new password.",
    })

@app.route("/api/auth/verifier/reset-password", methods=["POST"])
def reset_password():
    data    = request.get_json()
    token   = data.get("token","").strip()
    new_pwd = data.get("new_password","").strip()
    if len(new_pwd) < 6:
        return jsonify({"success": False, "error": "Password must be at least 6 characters"}), 400
    db         = load_db()
    token_data = db["reset_tokens"].get(token)
    if not token_data:
        return jsonify({"success": False, "error": "Invalid or expired token"}), 400
    if datetime.now() > datetime.fromisoformat(token_data["expires_at"]):
        del db["reset_tokens"][token]
        save_db(db)
        return jsonify({"success": False, "error": "Token has expired"}), 400
    db["verifiers"][token_data["username"]]["password"] = hash_password(new_pwd)
    del db["reset_tokens"][token]
    save_db(db)
    return jsonify({"success": True, "message": "Password reset successfully"})

@app.route("/api/auth/me", methods=["GET"])
def auth_me():
    if "role" in session:
        return jsonify({"logged_in": True,
                        "role": session["role"],
                        "username": session.get("username")})
    return jsonify({"logged_in": False})

# ══════════════════════════════════════════════════════════════════════════
# STORE (uploader only)
# ══════════════════════════════════════════════════════════════════════════
# ── REPLACE ONLY THE STORE ROUTE in your app.py with this ─────────────────
# Find the existing @app.route("/api/store") and replace the entire function

@app.route("/api/store", methods=["POST"])
def store():
    if session.get("role") != "uploader":
        return jsonify({"error": "Unauthorized"}), 401
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    cert_type = request.form.get("cert_type", "10")
    pdf_path  = save_file(request.files["file"])
    try:
        from store import extract_10th, extract_12th, store_on_blockchain
        result    = extract_10th(pdf_path) if cert_type == "10" else extract_12th(pdf_path)
        s         = result["student"]
        reg_no    = s.get("permanent_register_no") or s.get("number")
        comp_hash = result["hashes"]["composite_hash"]

        bc_result = store_on_blockchain(reg_no, cert_type, comp_hash)

        result["blockchain"] = {
            "tx_hash":        bc_result.get("tx_hash"),
            "network":        "Sepolia",
            "explorer":       (f"https://sepolia.etherscan.io/tx/{bc_result['tx_hash']}"
                               if bc_result.get("tx_hash") else None),
            "already_stored": bc_result.get("already_stored", False),
            "hash_conflict":  bc_result.get("hash_conflict", False),
            "message":        bc_result.get("message"),
        }
        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
# ══════════════════════════════════════════════════════════════════════════
# VERIFY DIGITAL (verifier only)
# ══════════════════════════════════════════════════════════════════════════

@app.route("/api/verify/digital", methods=["POST"])
def verify_digital():
    if session.get("role") != "verifier":
        return jsonify({"error": "Unauthorized"}), 401
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    cert_type = request.form.get("cert_type","10")
    pdf_path  = save_file(request.files["file"])
    try:
        from verify import (detect_pdf_type, ocr_extract,
                            table_extract_10th, table_extract_12th,
                            compute_hash, verify_on_blockchain)
        pdf_info = detect_pdf_type(pdf_path)
        student  = (ocr_extract(pdf_path, cert_type)
                    if pdf_info["is_image_based"]
                    else (table_extract_10th(pdf_path) if cert_type == "10"
                          else table_extract_12th(pdf_path)))
        missing = [f for f in ["name","permanent_register_no","session"]
                   if not student.get(f)]
        if missing:
            return jsonify({"error": f"Could not extract: {', '.join(missing)}. Check PDF quality."}), 400
        fresh_hash    = compute_hash(
            name        = student["name"],
            register_no = student["permanent_register_no"],
            total_marks = student["total_marks"],
            cert_type   = cert_type,
            session     = student["session"],
        )
        verify_result = verify_on_blockchain(
            student["permanent_register_no"], cert_type, fresh_hash)
        return jsonify({
            "success":       True,
            "student":       student,
            "fresh_hash":    fresh_hash,
            "verify_result": verify_result,
            "pdf_info":      pdf_info,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════════
# VERIFY SCANNED — QR + OCR field comparison
# ══════════════════════════════════════════════════════════════════════════

@app.route("/api/verify/scanned", methods=["POST"])
def verify_scanned():
    if session.get("role") != "verifier":
        return jsonify({"error": "Unauthorized"}), 401
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    pdf_path = save_file(request.files["file"])

    try:
        from qr_check import detect_qr_from_file, check_official_url

        # Step 1: QR detection
        qr_data = detect_qr_from_file(pdf_path)

        if qr_data is None:
            return jsonify({
                "success":  True,
                "qr_found": False,
                "verdict":  "NO_QR",
                "message":  "No QR code found in this certificate.",
                "fields":   [],
            })

        if not qr_data.startswith("http"):
            return jsonify({
                "success":  True,
                "qr_found": True,
                "qr_data":  qr_data,
                "verdict":  "INVALID_QR",
                "message":  "QR found but does not contain a URL.",
                "fields":   [],
            })

        # Step 2: URL validation
        domain_ok, path_ok = check_official_url(qr_data)

        if not (domain_ok and path_ok):
            return jsonify({
                "success":   True,
                "qr_found":  True,
                "qr_url":    qr_data,
                "domain_ok": domain_ok,
                "path_ok":   path_ok,
                "verdict":   "TAMPERED",
                "message":   "QR URL is not from the official portal. Certificate is likely fake.",
                "fields":    [],
            })

        # Step 3: OCR field comparison (QR URL is valid — now check fields)
                # Step 3: OCR field comparison (QR URL is valid — now check fields)
        try:
            from ocr_compare import compare_fields

            cert_type_for_ocr = request.form.get("cert_type", "10")
            ocr_result = compare_fields(pdf_path, qr_data, cert_type_for_ocr)

            return jsonify({
                "success":   True,
                "qr_found":  True,
                "qr_url":    qr_data,
                "domain_ok": domain_ok,
                "path_ok":   path_ok,
                "verdict":   ocr_result["verdict"],
                "fields":    ocr_result["fields"],
                "easyocr":   ocr_result["easyocr_used"],
                "message":   ("All fields match. Certificate appears genuine."
                              if ocr_result["verdict"] == "GENUINE"
                              else "One or more fields have been tampered."),
            })
        except Exception as e:
            # OCR failed — still report QR passed
            return jsonify({
                "success":   True,
                "qr_found":  True,
                "qr_url":    qr_data,
                "domain_ok": domain_ok,
                "path_ok":   path_ok,
                "verdict":   "QR_ONLY",
                "fields":    [],
                "message":   f"QR URL is valid. Field OCR check failed: {str(e)}",
            })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
if __name__ == "__main__":
    app.run(debug=False, port=5000)