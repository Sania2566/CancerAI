from flask import Flask, render_template, request, jsonify, redirect, session
import pandas as pd
from geopy.distance import geodesic
import pickle
import sqlite3
import os
from datetime import datetime, timedelta
import shutil
import requests
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

# ---------------- OCR (cloud-based, no server install needed) ---------------- #
# Report analysis uses the OCR.space cloud API instead of a locally-installed
# Tesseract binary, since most hosts (e.g. Render's native runtime) don't allow
# installing system packages. Get a free key (no credit card) at:
#   https://ocr.space/ocrapi/freekey
# Set it as the OCR_SPACE_API_KEY environment variable. Falls back to the
# public "helloworld" demo key, which is shared and rate-limited — fine for a
# quick test, but get your own key for real use.
OCR_SPACE_API_KEY = os.environ.get("OCR_SPACE_API_KEY", "helloworld")
OCR_SPACE_ENDPOINT = "https://api.ocr.space/parse/image"


def ocr_extract_text(file_path):
    """Send an image file to the OCR.space API and return the extracted text.
    Raises RuntimeError with a human-readable message on failure."""
    with open(file_path, "rb") as f:
        response = requests.post(
            OCR_SPACE_ENDPOINT,
            files={"file": f},
            data={
                "apikey": OCR_SPACE_API_KEY,
                "language": "eng",
                "OCREngine": 2,
                "scale": "true",
                "isTable": "false",
            },
            timeout=30,
        )

    if response.status_code == 403:
        raise RuntimeError(
            "OCR service rejected the request (403). This usually means "
            "OCR_SPACE_API_KEY is missing, invalid, or still set to the "
            "shared 'helloworld' demo key. Get a free key at "
            "https://ocr.space/ocrapi/freekey and set it as an environment "
            "variable."
        )

    response.raise_for_status()
    result = response.json()

    if result.get("IsErroredOnProcessing"):
        error_message = result.get("ErrorMessage") or ["Unknown OCR error"]
        if isinstance(error_message, list):
            error_message = "; ".join(error_message)
        raise RuntimeError(error_message)

    parsed_results = result.get("ParsedResults") or []
    if not parsed_results:
        raise RuntimeError("No text could be extracted from this image")

    return parsed_results[0].get("ParsedText", "")

app = Flask(__name__)
app.secret_key = "secret123"

# Google OAuth Client ID (from Google Cloud Console -> APIs & Services -> Credentials).
# Set this as an environment variable in production; the literal string below
# is only a local-development fallback and must be replaced with your own ID.
GOOGLE_CLIENT_ID = os.environ.get(
    "GOOGLE_CLIENT_ID",
    "290251344819-tbr69ghn9vti71s5j5dt1l63loka3cgh.apps.googleusercontent.com"
)

# ---------------- DATABASE ---------------- #

def init_db():

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute("""
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    email TEXT UNIQUE,
    password TEXT
)
""")

    cursor.execute("""
CREATE TABLE IF NOT EXISTS profiles(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT,
    age TEXT,
    smoking TEXT,
    weight_loss TEXT,
    cough TEXT,
    fatigue TEXT,
    lump TEXT,
    bleeding TEXT,
    swallowing TEXT,
    exercise TEXT,
    diet TEXT,
    cancer TEXT,
    cancer_type TEXT,
    cancer_stage TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")

    cursor.execute("""
CREATE TABLE IF NOT EXISTS report_history(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT,
    filename TEXT,
    extracted_text TEXT,
    summary TEXT,
    keywords TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")

    cursor.execute("""
CREATE TABLE IF NOT EXISTS symptom_logs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT,
    age TEXT,
    smoking TEXT,
    weight_loss TEXT,
    cough TEXT,
    fatigue TEXT,
    family_history TEXT,
    alcohol TEXT,
    fever_sweats TEXT,
    cough_blood TEXT,
    lump TEXT,
    skin_change TEXT,
    bleeding TEXT,
    bowel_bladder TEXT,
    swallowing TEXT,
    risk INTEGER,
    severity TEXT,
    condition TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")

    conn.commit()
    conn.close()

init_db()

def migrate_db():
    """Adds columns introduced after the initial table creation, for
    databases that already existed before this column was added."""
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(profiles)")
    columns = [row[1] for row in cursor.fetchall()]

    if "created_at" not in columns:
        cursor.execute("ALTER TABLE profiles ADD COLUMN created_at TEXT")
        # Backfill existing rows so they still appear under "All Time"
        cursor.execute(
            "UPDATE profiles SET created_at = ? WHERE created_at IS NULL",
            (datetime.now().isoformat(sep=" ", timespec="seconds"),)
        )
        conn.commit()

    cursor.execute("PRAGMA table_info(symptom_logs)")
    symptom_columns = [row[1] for row in cursor.fetchall()]

    new_symptom_columns = [
        "family_history", "alcohol", "fever_sweats",
        "cough_blood", "lump", "skin_change", "bleeding",
        "bowel_bladder", "swallowing"
    ]
    for col in new_symptom_columns:
        if col not in symptom_columns:
            cursor.execute(f"ALTER TABLE symptom_logs ADD COLUMN {col} TEXT")
    conn.commit()

    conn.close()

migrate_db()

# ---------------- LOAD DATA ---------------- #

hospitals_df = pd.read_csv("data/hospitals.csv")
df = pd.read_csv("data/cancer_dataset.csv")

model = pickle.load(open("cancer_model.pkl", "rb"))

# ---------------- HOME ---------------- #

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/signup", methods=["POST"])
def signup():

    name = request.form["name"]
    email = request.form["email"]
    password = request.form["password"]

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO users(name,email,password) VALUES(?,?,?)",
            (name,email,password)
        )

        conn.commit()

    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"success": False, "message": "Email already exists"}), 409

    conn.close()

    return jsonify({
        "success": True,
        "message": "Account created successfully",
        "name": name,
        "redirect": "/login"
    })

@app.route("/login", methods=["POST"])
def login():

    email = request.form["email"]
    password = request.form["password"]

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM users WHERE email=? AND password=?",
        (email,password)
    )

    user = cursor.fetchone()

    if not user:
        conn.close()
        return jsonify({"success": False, "message": "Invalid email or password"}), 401

    # Check if this user has already completed profile setup
    cursor.execute(
        "SELECT id FROM profiles WHERE email=?",
        (email,)
    )
    existing_profile = cursor.fetchone()

    conn.close()

    session["email"] = email

    next_page = "/analysis" if existing_profile else "/profile_setup"

    return jsonify({
        "success": True,
        "message": "Login successful",
        "name": user[1],
        "redirect": next_page
    })

@app.route("/auth/google", methods=["POST"])
def auth_google():
    data = request.get_json(silent=True) or {}
    credential = data.get("credential")

    if not credential:
        return jsonify({"success": False, "message": "Missing Google credential"}), 400

    if not GOOGLE_CLIENT_ID or GOOGLE_CLIENT_ID.startswith("YOUR_GOOGLE_CLIENT_ID"):
        return jsonify({
            "success": False,
            "message": "Google sign-in isn't configured yet. Set GOOGLE_CLIENT_ID on the server."
        }), 500

    try:
        idinfo = google_id_token.verify_oauth2_token(
            credential, google_requests.Request(), GOOGLE_CLIENT_ID
        )
    except ValueError as e:
        print(f"[Google Sign-In] Token verification failed: {e}")
        return jsonify({"success": False, "message": f"Invalid Google credential: {e}"}), 401

    email = idinfo.get("email")
    name = idinfo.get("name") or (email.split("@")[0] if email else "Google User")

    if not email:
        return jsonify({"success": False, "message": "Your Google account has no email address"}), 400

    if not idinfo.get("email_verified", True):
        return jsonify({"success": False, "message": "Please verify your Google email address first"}), 400

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE email=?", (email,))
    user = cursor.fetchone()

    if not user:
        # New account via Google — no password since Google handles auth.
        cursor.execute(
            "INSERT INTO users(name,email,password) VALUES(?,?,?)",
            (name, email, None)
        )
        conn.commit()

    cursor.execute("SELECT id FROM profiles WHERE email=?", (email,))
    existing_profile = cursor.fetchone()
    conn.close()

    session["email"] = email
    next_page = "/analysis" if existing_profile else "/profile_setup"

    return jsonify({
        "success": True,
        "message": "Signed in with Google",
        "name": name,
        "redirect": next_page
    })

@app.route("/profile_setup")
def profile_setup():

    if "email" not in session:
        return redirect("/")

    email = session["email"]

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM profiles WHERE email=?", (email,))
    existing_profile = cursor.fetchone()
    conn.close()

    if existing_profile:
        return redirect("/analysis")

    return render_template("profile_setup.html", email=email)

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


@app.route("/save_profile", methods=["POST"])
def save_profile():

    if "email" not in session:
        return redirect("/")

    email = request.form["email"]
    age = request.form["age"]
    smoking = request.form["smoking"]
    weight_loss = request.form["weight_loss"]
    cough = request.form["cough"]
    fatigue = request.form["fatigue"]
    lump = request.form["lump"]
    bleeding = request.form["bleeding"]
    swallowing = request.form["swallowing"]
    exercise = request.form["exercise"]
    diet = request.form["diet"]

    cancer = request.form["cancer"]
    cancer_type = request.form.get("cancer_type")
    cancer_stage = request.form.get("cancer_stage")

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM profiles WHERE email=?", (email,))
    if cursor.fetchone():
        conn.close()
        return redirect("/analysis")

    cursor.execute("""
    INSERT INTO profiles
    (email, age, smoking, weight_loss, cough, fatigue, lump,
     bleeding, swallowing, exercise, diet, cancer, cancer_type, cancer_stage)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """,
    (email, age, smoking, weight_loss, cough, fatigue, lump,
     bleeding, swallowing, exercise, diet, cancer, cancer_type, cancer_stage))

    conn.commit()
    conn.close()

    return redirect("/analysis")

@app.route("/profile")
def view_profile():

    email = session.get("email")

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute("""
SELECT users.name, users.email,
       profiles.age, profiles.smoking, profiles.weight_loss,
       profiles.cough, profiles.fatigue, profiles.lump,
       profiles.bleeding, profiles.swallowing,
       profiles.exercise, profiles.diet,
       profiles.cancer, profiles.cancer_type, profiles.cancer_stage
FROM users
JOIN profiles ON users.email = profiles.email
WHERE users.email=?
""", (email,))

    profile = cursor.fetchone()

    conn.close()

    return render_template("profile.html", profile=profile)

# ---------------- SYMPTOM ANALYSIS ---------------- #

@app.route("/analysis")
def analysis():
    if "email" not in session:
        return redirect("/")
    return render_template("index.html")


@app.route("/analyze_symptoms", methods=["POST"])
def analyze_symptoms():

    data = request.get_json() or {}

    # ------------------------------------------------------------------
    # Each answer carries a base point value. Points are grouped into
    # clinical categories so the response can show *where* risk is
    # coming from, not just a single number. A handful of well-known
    # symptom *combinations* add extra points on top of the per-answer
    # base score, since real risk assessment isn't just additive -
    # e.g. smoking + a persistent cough is materially more concerning
    # than either alone.
    # ------------------------------------------------------------------

    # category -> list of (points, max_points) so we can compute a % per category
    categories = {
        "demographics":  {"points": 0, "max": 0, "label": "Demographics & History"},
        "lifestyle":      {"points": 0, "max": 0, "label": "Lifestyle Risk Factors"},
        "systemic":       {"points": 0, "max": 0, "label": "Systemic Symptoms"},
        "respiratory":    {"points": 0, "max": 0, "label": "Respiratory Signs"},
        "structural":     {"points": 0, "max": 0, "label": "Lumps & Skin Changes"},
        "gi_urogenital":  {"points": 0, "max": 0, "label": "GI / Urogenital Signs"},
    }

    flags = []  # human-readable flagged factors shown as chips in the UI

    def score(category, key, mapping, max_pts):
        """mapping: dict of answer -> points. Adds to category totals and
        returns the points actually scored for this answer."""
        categories[category]["max"] += max_pts
        val = data.get(key)
        pts = mapping.get(val, 0)
        categories[category]["points"] += pts
        return pts, val

    # ── Demographics & history ──
    age_pts, age_val = score("demographics", "age", {
        "Below 30": 0, "30–45": 4, "45–60": 9, "Above 60": 14
    }, 14)

    fam_pts, fam_val = score("demographics", "family_history", {
        "No": 0, "One relative": 8, "Multiple relatives": 16
    }, 16)
    if fam_val == "Multiple relatives":
        flags.append({"text": "Strong family history of cancer", "level": "high"})
    elif fam_val == "One relative":
        flags.append({"text": "Family history of cancer", "level": "warn"})

    # ── Lifestyle ──
    smoke_pts, smoke_val = score("lifestyle", "smoking", {
        "Never": 0, "Former smoker": 6, "Occasional": 10, "Regular / heavy": 20
    }, 20)
    if smoke_val == "Regular / heavy":
        flags.append({"text": "Regular/heavy smoking", "level": "high"})
    elif smoke_val == "Occasional":
        flags.append({"text": "Occasional smoking", "level": "warn"})

    alc_pts, alc_val = score("lifestyle", "alcohol", {
        "Rarely / never": 0, "Occasionally": 4, "Frequently (most days)": 10
    }, 10)

    # ── Systemic / constitutional symptoms ──
    wl_pts, wl_val = score("systemic", "weight_loss", {
        "No": 0, "Slight (1–3 kg)": 8, "Significant (5kg+ without trying)": 18
    }, 18)
    if wl_val == "Significant (5kg+ without trying)":
        flags.append({"text": "Significant unexplained weight loss", "level": "high"})

    fat_pts, fat_val = score("systemic", "fatigue", {
        "No": 0, "Sometimes": 5, "Often, most days": 11
    }, 11)

    fs_pts, fs_val = score("systemic", "fever_sweats", {
        "No": 0, "Occasionally": 6, "Recurrent / nightly": 14
    }, 14)
    if fs_val == "Recurrent / nightly":
        flags.append({"text": "Recurrent fevers or night sweats", "level": "high"})

    # ── Respiratory ──
    cough_pts, cough_val = score("respiratory", "cough", {
        "No": 0, "Less than 3 weeks": 4, "More than 3 weeks": 14
    }, 14)
    if cough_val == "More than 3 weeks":
        flags.append({"text": "Cough lasting more than 3 weeks", "level": "warn"})

    cb_pts, cb_val = score("respiratory", "cough_blood", {
        "No": 0, "Mild breathlessness only": 8, "Blood in cough / severe breathlessness": 22
    }, 22)
    if cb_val == "Blood in cough / severe breathlessness":
        flags.append({"text": "Blood in cough or severe breathlessness", "level": "high"})

    # ── Lumps / skin / structural ──
    lump_pts, lump_val = score("structural", "lump", {
        "No": 0, "Small, unchanged lump": 7, "Growing or hard lump": 20
    }, 20)
    if lump_val == "Growing or hard lump":
        flags.append({"text": "Growing or hard lump", "level": "high"})

    skin_pts, skin_val = score("structural", "skin_change", {
        "No": 0, "Slight change": 6, "Noticeable change or new irregular spot": 16
    }, 16)
    if skin_val == "Noticeable change or new irregular spot":
        flags.append({"text": "Noticeable mole/skin change", "level": "high"})

    # ── GI / urogenital ──
    bleed_pts, bleed_val = score("gi_urogenital", "bleeding", {
        "No": 0, "Once, minor": 8, "Repeated or noticeable bleeding": 18
    }, 18)
    if bleed_val == "Repeated or noticeable bleeding":
        flags.append({"text": "Repeated or noticeable unexplained bleeding", "level": "high"})

    bb_pts, bb_val = score("gi_urogenital", "bowel_bladder", {
        "No": 0, "Mild change": 6, "Persistent change": 14
    }, 14)

    sw_pts, sw_val = score("gi_urogenital", "swallowing", {
        "No": 0, "Occasionally": 5, "Frequently / worsening": 13
    }, 13)
    if sw_val == "Frequently / worsening":
        flags.append({"text": "Frequent or worsening difficulty swallowing", "level": "warn"})

    base_points = (age_pts + fam_pts + smoke_pts + alc_pts + wl_pts + fat_pts +
                   fs_pts + cough_pts + cb_pts + lump_pts + skin_pts +
                   bleed_pts + bb_pts + sw_pts)

    # ------------------------------------------------------------------
    # Combination logic — certain symptom pairings are clinically more
    # concerning together than the sum of their individual points would
    # suggest, so we add a modest compounding bonus when they co-occur.
    # ------------------------------------------------------------------
    combo_bonus = 0
    combo_notes = []

    if smoke_val in ("Occasional", "Regular / heavy") and cough_val == "More than 3 weeks":
        combo_bonus += 10
        combo_notes.append({"text": "Smoking + prolonged cough", "level": "high"})

    if wl_val == "Significant (5kg+ without trying)" and fat_val == "Often, most days":
        combo_bonus += 8
        combo_notes.append({"text": "Weight loss combined with persistent fatigue", "level": "high"})

    if fs_val == "Recurrent / nightly" and wl_val != "No":
        combo_bonus += 8
        combo_notes.append({"text": "Night sweats combined with weight loss", "level": "high"})

    if lump_val == "Growing or hard lump" and fam_val in ("One relative", "Multiple relatives"):
        combo_bonus += 6
        combo_notes.append({"text": "Lump with family history of cancer", "level": "high"})

    if age_val == "Above 60" and (bleed_val != "No" or bb_val != "No"):
        combo_bonus += 6
        combo_notes.append({"text": "Bleeding/bowel changes at an older age", "level": "warn"})

    flags.extend(combo_notes)

    raw_total = base_points + combo_bonus
    # Theoretical max if everything scored worst-case + every combo triggered
    max_total = sum(c["max"] for c in categories.values()) + 38  # 38 = sum of combo bonuses above
    risk = round(min(100, (raw_total / max_total) * 100)) if max_total else 0

    # ------------------------------------------------------------------
    # Build the per-category percentage breakdown for the UI.
    # ------------------------------------------------------------------
    category_breakdown = {}
    for key, c in categories.items():
        pct = round((c["points"] / c["max"]) * 100) if c["max"] else 0
        category_breakdown[key] = {"pct": pct, "label": c["label"]}

    # ------------------------------------------------------------------
    # Determine the dominant concern area (highest-scoring category) so
    # "condition" reflects an actual pattern in the answers instead of a
    # generic phrase.
    # ------------------------------------------------------------------
    dominant_key = max(category_breakdown, key=lambda k: category_breakdown[k]["pct"])
    dominant_pct = category_breakdown[dominant_key]["pct"]

    condition_map = {
        "demographics":  "Age and family-history risk factors are prominent",
        "lifestyle":      "Lifestyle-related risk factors (smoking/alcohol) are prominent",
        "systemic":       "Systemic symptoms (weight loss, fatigue, fevers) are prominent",
        "respiratory":    "Respiratory warning signs are prominent",
        "structural":      "Lump or skin-change warning signs are prominent",
        "gi_urogenital":  "GI / urogenital warning signs are prominent",
    }

    if dominant_pct == 0:
        condition = "No significant risk patterns detected"
    else:
        condition = condition_map.get(dominant_key, "Some risk factors detected")

    # ------------------------------------------------------------------
    # Severity bands and tailored advice. Advice references the actual
    # flagged factors instead of one generic sentence per band.
    # ------------------------------------------------------------------
    has_high_flag = any(f["level"] == "high" for f in flags)

    if risk < 25 and not has_high_flag:
        severity = "Low"
        advice = ("Your responses show few notable warning signs right now. Keep up routine "
                  "check-ups, stay alert to any new or worsening symptoms, and maintain a "
                  "healthy lifestyle (balanced diet, regular activity, avoiding tobacco).")

    elif risk < 50 and not has_high_flag:
        severity = "Moderate"
        top_cats = sorted(category_breakdown.items(), key=lambda kv: kv[1]["pct"], reverse=True)[:2]
        cat_names = " and ".join(category_breakdown[k]["label"] for k, v in top_cats if v["pct"] > 0)
        advice = (f"A few factors stand out, particularly around {cat_names or 'the symptoms you reported'}. "
                  "These are not necessarily signs of cancer, but it's worth discussing them with a "
                  "doctor at your next visit, especially if they persist or worsen.")

    elif risk < 70 or (has_high_flag and risk < 80):
        severity = "High"
        advice = ("Several symptoms together raise enough concern that we'd recommend scheduling "
                  "an appointment with a doctor in the near future for a proper evaluation, rather "
                  "than waiting for a routine check-up.")

    else:
        severity = "Very High"
        advice = ("Multiple serious warning signs were reported together. Please consult a doctor "
                  "as soon as possible for a thorough evaluation. Early assessment significantly "
                  "improves outcomes for most conditions, including cancer.")

    # ------------------------------------------------------------------
    # Urgent banner — shown only when specific red-flag combinations or
    # severe single symptoms are present, regardless of overall risk %.
    # ------------------------------------------------------------------
    urgent = None
    severe_single_flags = [f for f in flags if f["level"] == "high"]
    if cb_val == "Blood in cough / severe breathlessness":
        urgent = ("Blood in cough or severe breathlessness can have several causes, some of which "
                  "need urgent attention. Please seek medical care promptly.")
    elif bleed_val == "Repeated or noticeable bleeding":
        urgent = ("Repeated or noticeable unexplained bleeding should be evaluated by a doctor "
                  "promptly rather than monitored at home.")
    elif lump_val == "Growing or hard lump" and skin_val == "Noticeable change or new irregular spot":
        urgent = ("A growing/hard lump together with a changing skin spot is a combination worth "
                  "getting checked by a doctor soon.")
    elif len(severe_single_flags) >= 3:
        urgent = ("Multiple high-concern symptoms were reported together. We strongly recommend "
                  "seeing a doctor soon for a full evaluation.")

    # Persist this submission so the dashboard can reflect real, live data
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO symptom_logs
        (email, age, smoking, weight_loss, cough, fatigue,
         family_history, alcohol, fever_sweats, cough_blood,
         lump, skin_change, bleeding, bowel_bladder, swallowing,
         risk, severity, condition)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        session.get("email"),
        data.get("age"),
        data.get("smoking"),
        data.get("weight_loss"),
        data.get("cough"),
        data.get("fatigue"),
        data.get("family_history"),
        data.get("alcohol"),
        data.get("fever_sweats"),
        data.get("cough_blood"),
        data.get("lump"),
        data.get("skin_change"),
        data.get("bleeding"),
        data.get("bowel_bladder"),
        data.get("swallowing"),
        risk,
        severity,
        condition
    ))
    conn.commit()
    conn.close()

    return jsonify({
        "risk": risk,
        "severity": severity,
        "condition": condition,
        "advice": advice,
        "categories": category_breakdown,
        "flags": flags,
        "urgent": urgent
    })

# ---------------- WHO GLOBAL CANCER STATS ---------------- #
#
# Pulls real, published figures from WHO's Global Health Observatory (GHO)
# OData API — a free, public, no-auth API at https://ghoapi.azureedge.net/api.
# This is genuine published WHO data, not a live feed: GLOBOCAN/WHO cancer
# estimates are produced annually, and the GHO platform itself is refreshed
# roughly every 1-2 weeks per WHO's own documentation. There is no public
# source anywhere that reports cancer diagnoses in real time, so this cache
# is refreshed periodically (not every 30s) and is clearly distinct from
# the live, real-time data drawn from THIS app's own users.

GHO_API_BASE = "https://ghoapi.azureedge.net/api"
WHO_CACHE_TTL = timedelta(hours=6)

_who_cache = {
    "data": None,
    "fetched_at": None,
    "error": None,
}

# Verified indicator codes that genuinely exist on the WHO GHO API and
# relate to cancer. The GHO API does not carry raw "new cancer cases"
# incidence counts (those live only on IARC's separate GLOBOCAN/Cancer
# Today platform, gco.iarc.who.int, which has no public API) — so these
# are the real cancer-related figures GHO actually publishes: screening
# program coverage, national policy existence, and mortality risk.
# Verified directly against https://ghoapi.azureedge.net/api/Indicator.
CANCER_INDICATORS = [
    ("NCDMORT3070", "Probability of dying age 30-70 from cancer, CVD, diabetes or chronic respiratory disease (%)"),
    ("NCD_CCS_cervicalcancerpgmcvg", "Countries with a national cervical cancer screening program (coverage, %)"),
    ("NCD_CCS_BreastCancer", "Countries with breast cancer screening at the primary care level"),
    ("NCD_CCS_BowelCancer", "Countries with colon cancer screening at the primary care level"),
    ("NCD_CCS_CancerRegNational", "Countries with a population-based cancer registry"),
    ("NCD_CCS_CancerPlan", "Countries with an operational national cancer policy/action plan"),
]


def _fetch_who_cancer_indicators():
    """Pulls the most recent global value for each verified cancer
    indicator on the WHO GHO API. Returns a list of
    {name, year, value, country} dicts, or raises on failure so the caller
    can fall back to the last good cache."""

    results = []

    for code, friendly_name in CANCER_INDICATORS:
        try:
            data_resp = requests.get(f"{GHO_API_BASE}/{code}", timeout=10)
            data_resp.raise_for_status()
            rows = data_resp.json().get("value", [])
        except requests.RequestException:
            continue

        if not rows:
            continue

        # Prefer a world-level row if present, else average/aggregate
        # the most recent year's country-level rows so we show one
        # meaningful global figure rather than a single country's value.
        world_rows = [r for r in rows if r.get("SpatialDim") == "WORLD"]

        if world_rows:
            latest = max(world_rows, key=lambda r: (r.get("TimeDim") or 0))
            value = latest.get("NumericValue")
            year = latest.get("TimeDim")
            country = "Global"
        else:
            numeric_rows = [r for r in rows if r.get("NumericValue") is not None]
            if not numeric_rows:
                continue
            latest_year = max(r.get("TimeDim") or 0 for r in numeric_rows)
            year_rows = [r for r in numeric_rows if r.get("TimeDim") == latest_year]
            value = sum(r["NumericValue"] for r in year_rows) / len(year_rows)
            year = latest_year
            country = f"avg. across {len(year_rows)} reporting countries"

        if value is None:
            continue

        results.append({
            "name": friendly_name,
            "code": code,
            "year": year,
            "value": value,
            "country": country,
        })

    return results


def get_who_global_stats(force=False):
    """Returns cached WHO cancer stats, refreshing in the background only
    when the cache is stale (or force=True). Never blocks the dashboard on
    a failed WHO request — falls back to the last known good cache, or a
    clear error state if there's never been a successful fetch."""

    now = datetime.now()
    is_stale = (
        _who_cache["fetched_at"] is None
        or now - _who_cache["fetched_at"] > WHO_CACHE_TTL
    )

    if force or is_stale:
        try:
            fresh = _fetch_who_cancer_indicators()
            if fresh:
                _who_cache["data"] = fresh
                _who_cache["fetched_at"] = now
                _who_cache["error"] = None
        except requests.RequestException as e:
            # Keep serving the last good cache; just record the error
            _who_cache["error"] = str(e)

    return {
        "indicators": _who_cache["data"] or [],
        "last_updated": _who_cache["fetched_at"].isoformat() if _who_cache["fetched_at"] else None,
        "source": "WHO Global Health Observatory (GHO)",
        "source_url": "https://www.who.int/data/gho",
        "error": _who_cache["error"] if not _who_cache["data"] else None,
    }


@app.route("/global_stats")
def global_stats():
    """JSON endpoint for the dashboard's 'Global Reference' section. Cheap
    to call often since it's served from cache; the underlying WHO data
    itself only changes on WHO's own publication schedule."""
    return jsonify(get_who_global_stats())


# ---------------- DASHBOARD ---------------- #

df["Diagnosis_Date"] = pd.to_datetime(df["Diagnosis_Date"], errors="coerce")
df["Year"] = df["Diagnosis_Date"].dt.year


def _range_cutoff(range_key):
    """Returns the earliest datetime to include for a given range key,
    or None to include everything (All Time)."""
    now = datetime.now()
    if range_key == "30d":
        return now - timedelta(days=30)
    if range_key == "1y":
        return now - timedelta(days=365)
    if range_key == "5y":
        return now - timedelta(days=365 * 5)
    return None  # "all"


def get_dashboard_data(range_key="all"):
    """Builds chart datasets by blending the static reference dataset with
    real, live data collected from user profiles and symptom-analysis
    submissions, filtered to the requested date range. Each user
    contribution adds +1 to its matching category."""

    cutoff = _range_cutoff(range_key)

    # --- Filter the static reference dataset by Diagnosis_Date ---
    filtered_df = df if cutoff is None else df[df["Diagnosis_Date"] >= cutoff]

    cancer_counts = filtered_df["Cancer_Type"].value_counts().to_dict()
    smoking_counts = filtered_df["Smoking_Status"].value_counts().to_dict()
    treatment_counts = filtered_df["Treatment_Type"].value_counts().to_dict()

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    # --- Blend in completed health profiles (cancer type + smoking habit) ---
    cursor.execute("SELECT smoking, cancer, cancer_type, created_at FROM profiles")
    for smoking, cancer, cancer_type, created_at in cursor.fetchall():

        if cutoff is not None:
            try:
                if datetime.fromisoformat(str(created_at)[:19]) < cutoff:
                    continue
            except ValueError:
                continue

        if cancer == "Yes" and cancer_type:
            cancer_counts[cancer_type] = cancer_counts.get(cancer_type, 0) + 1

        if smoking:
            smoking_counts[smoking] = smoking_counts.get(smoking, 0) + 1

    # --- Blend in symptom-analysis submissions (smoking habit) ---
    cursor.execute("SELECT smoking, created_at FROM symptom_logs")
    symptom_rows = []
    for smoking, created_at in cursor.fetchall():

        row_dt = None
        if created_at:
            try:
                row_dt = datetime.fromisoformat(str(created_at)[:19])
            except ValueError:
                row_dt = None

        if cutoff is not None and (row_dt is None or row_dt < cutoff):
            continue

        if smoking:
            smoking_counts[smoking] = smoking_counts.get(smoking, 0) + 1

        symptom_rows.append(row_dt)

    conn.close()

    # --- Build the time-series chart. "Last 30 Days" buckets by day since a
    # single year-bucket would be meaningless at that range; everything else
    # buckets by year. ---
    if range_key == "30d":
        today = datetime.now().date()
        day_buckets = {(today - timedelta(days=i)): 0 for i in range(29, -1, -1)}

        for d in filtered_df["Diagnosis_Date"].dropna():
            d = d.date()
            if d in day_buckets:
                day_buckets[d] += 1

        for row_dt in symptom_rows:
            if row_dt and row_dt.date() in day_buckets:
                day_buckets[row_dt.date()] += 1

        time_labels = [d.strftime("%b %d") for d in day_buckets.keys()]
        time_values = [int(v) for v in day_buckets.values()]

    else:
        yearly_counts = filtered_df.groupby("Year").size().to_dict()

        for row_dt in symptom_rows:
            if row_dt:
                yearly_counts[row_dt.year] = yearly_counts.get(row_dt.year, 0) + 1

        sorted_years = sorted(int(y) for y in yearly_counts.keys())
        time_labels = [str(y) for y in sorted_years]
        time_values = [int(yearly_counts[y]) for y in sorted_years]

    return {
        "cancer_labels": list(cancer_counts.keys()),
        "cancer_values": [int(v) for v in cancer_counts.values()],

        "smoking_labels": list(smoking_counts.keys()),
        "smoking_values": [int(v) for v in smoking_counts.values()],

        "treatment_labels": list(treatment_counts.keys()),
        "treatment_values": [int(v) for v in treatment_counts.values()],

        "year_labels": time_labels,
        "year_values": time_values,
    }


VALID_RANGES = {"all", "5y", "1y", "30d"}


@app.route("/dashboard")
def dashboard():
    range_key = request.args.get("range", "all")
    if range_key not in VALID_RANGES:
        range_key = "all"
    return render_template("dashboard.html", selected_range=range_key, **get_dashboard_data(range_key))


@app.route("/dashboard_data")
def dashboard_data():
    """JSON endpoint the dashboard polls/calls to refresh charts and stat
    cards for a given date range, without a full page reload."""
    range_key = request.args.get("range", "all")
    if range_key not in VALID_RANGES:
        range_key = "all"
    return jsonify(get_dashboard_data(range_key))


# ---------------- CHATBOT ---------------- #

@app.route("/chatbot")
def chatbot():
    return render_template("chatbot.html")

@app.route("/chat", methods=["POST"])
def chat():

    data = request.get_json()
    message = data.get("message")

    reply = chatbot_response(message)

    return jsonify({"reply": reply})


def chatbot_response(user_input):

    user_input = user_input.lower()

    # greetings
    if "hello" in user_input or "hi" in user_input:
        return "Hello! I'm here to help with basic health questions. Tell me how you're feeling."

    # stomach
    elif "stomach" in user_input:
        return ("Stomach pain can happen due to gas, indigestion, or irregular meals. "
                "Try drinking warm water and eating light food. "
                "If pain becomes severe or lasts many hours, it would be good to consult a doctor.")

    # headache
    elif "headache" in user_input:
        return ("Headaches can occur due to stress, dehydration, or lack of sleep. "
                "Rest in a quiet place and drink enough water. "
                "If headaches happen frequently or become severe, consider consulting a doctor.")

    # fever
    elif "fever" in user_input:
        return ("Mild fever can happen due to infections or fatigue. "
                "Take rest, drink fluids, and eat light food. "
                "If fever stays high for more than 2 days, consulting a doctor is recommended.")

    # cough
    elif "cough" in user_input:
        return ("Cough is often caused by cold or throat irritation. "
                "Drink warm fluids and take rest. "
                "If cough lasts more than a week, a doctor should evaluate it.")

    # weakness
    elif "weakness" in user_input:
        return ("Weakness may occur due to lack of sleep, dehydration, or poor nutrition. "
                "Make sure you rest well, drink water, and eat balanced meals.")

    # dizziness
    elif "dizzy" in user_input:
        return ("Dizziness can happen due to dehydration, low blood pressure, or fatigue. "
                "Sit down, drink water, and rest for a while.")

    # vomiting
    elif "vomit" in user_input or "nausea" in user_input:
        return ("Nausea or vomiting can occur due to food irritation or infection. "
                "Drink small sips of water and avoid heavy food. "
                "If vomiting continues, consult a doctor.")

    # diarrhea
    elif "diarrhea" in user_input or "loose motion" in user_input:
        return ("Loose motion can cause dehydration. "
                "Drink ORS solution, water, and eat light foods like banana or rice. "
                "If it continues for long, consult a healthcare professional.")

    # possible cancer related symptom
    elif "lump" in user_input:
        return ("Sometimes lumps occur due to infection or swelling and are not serious. "
                "However if a lump persists, grows, or feels unusual, it is best to consult a doctor.")

    elif "weight loss" in user_input:
        return ("Unexplained weight loss can happen due to many reasons like stress, digestion issues, or illness. "
            "If the weight loss continues without trying, consider consulting a doctor to understand the cause.")

    elif "blood in stool" in user_input or "rectal bleeding" in user_input:
        return ("Blood in stool can sometimes be caused by minor conditions like hemorrhoids or infections. "
            "If this symptom occurs repeatedly or with pain, it is recommended to consult a doctor.")

    elif "difficulty swallowing" in user_input:
        return ("Difficulty swallowing may occur due to throat infections or irritation. "
            "If it continues for several days or worsens, it is best to consult a healthcare professional.")

    elif "persistent cough" in user_input:
        return ("A cough lasting many weeks may occur due to allergies, infections, or other conditions. "
            "If the cough persists for a long time, a doctor should evaluate it.")

    elif "unusual bleeding" in user_input:
        return ("Unusual bleeding can occur due to several health conditions. "
            "If bleeding happens without a clear reason or continues, consulting a doctor is recommended.")

    elif "skin change" in user_input or "mole change" in user_input:
        return ("Skin changes or mole changes are often harmless. "
            "However, if a mole changes shape, color, or size, it is best to get it checked by a doctor.")

    elif "chronic fatigue" in user_input:
        return ("Feeling tired for long periods can happen due to stress, poor sleep, or nutrition issues. "
            "If fatigue continues for weeks despite rest, consulting a healthcare professional may help.")


    else:
        return ("I can help with common health questions like fever, headache, stomach pain, cough, "
                "weakness, or dehydration. "
                "Tell me your symptoms and I'll try to guide you.")





# ---------------- HOSPITAL FINDER ---------------- #

@app.route("/hospitals")
def hospitals():
    return render_template("hospitals.html")


@app.route("/nearest_hospitals", methods=["POST"])
def nearest_hospitals():

    data = request.get_json()
    user_lat = float(data["lat"])
    user_lon = float(data["lon"])

    results = []

    for _, row in hospitals_df.iterrows():

        hospital_location = (row["latitude"], row["longitude"])
        user_location = (user_lat, user_lon)

        distance = geodesic(user_location, hospital_location).km

        results.append({
            "name": row["name"],
            "city": row["city"],
            "country": row["country"],
            "rating": row["rating"],
            "distance": round(distance, 2),
            "lat": float(row["latitude"]),
            "lon": float(row["longitude"]),
            "maps": f"https://www.google.com/maps/search/{row['name']}"
        })

    results = sorted(results, key=lambda x: x["distance"])

    return jsonify(results[:5])


# ---------------- AWARENESS PAGE ---------------- #

@app.route("/awareness")
def awareness():
    return render_template("awareness.html")


# ---------------- REPORT ANALYZER ---------------- #

UPLOAD_FOLDER = "uploads"

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


@app.route("/report-analyzer")
def report_page():
    return render_template("report_analyzer.html")


def extract_keywords(text_lower):
    """Extract key medical signals from report text as a list."""
    signals = []
    checks = [
        ("malignant", "Malignant"),
        ("benign", "Benign"),
        ("carcinoma", "Carcinoma"),
        ("cancer", "Cancer"),
        ("tumor", "Tumor"),
        ("stage", "Stage mentioned"),
        ("metastasis", "Metastasis"),
        ("lymph node", "Lymph node involvement"),
        ("normal", "Normal findings"),
        ("negative", "Negative result"),
        ("positive", "Positive result"),
        ("chemotherapy", "Chemotherapy"),
        ("radiation", "Radiation"),
        ("surgery", "Surgery"),
    ]
    for keyword, label in checks:
        if keyword in text_lower:
            signals.append(label)
    return signals


def classify_report(text_lower):
    if "malignant" in text_lower or "carcinoma" in text_lower or "cancer" in text_lower:
        return "⚠️ Report indicates possible malignant or cancer-related findings. Please consult an oncologist.", "danger"
    elif "benign" in text_lower:
        return "✅ Report suggests benign (non-cancerous) findings.", "positive"
    elif "tumor" in text_lower:
        return "⚠️ Tumor mentioned in report. Medical evaluation recommended.", "warning"
    else:
        return "❗ No clear diagnosis detected from report text.", "neutral"


def build_comparison(current_keywords, history_rows):
    """Compare current report to most recent previous one and return a narrative."""
    if not history_rows:
        return None

    prev = history_rows[0]  # most recent previous report
    prev_date = prev[5][:10]
    prev_keywords = [k.strip() for k in prev[4].split(",")] if prev[4] else []

    gained = [k for k in current_keywords if k not in prev_keywords]
    lost   = [k for k in prev_keywords if k not in current_keywords]
    same   = [k for k in current_keywords if k in prev_keywords]

    lines = [f"Compared to your report on <b>{prev_date}</b>:"]

    if gained:
        lines.append(f"🆕 <b>New findings:</b> {', '.join(gained)}")
    if lost:
        lines.append(f"✅ <b>Resolved / no longer present:</b> {', '.join(lost)}")
    if same:
        lines.append(f"📌 <b>Unchanged:</b> {', '.join(same)}")

    # Trend assessment
    danger_words = {"Malignant", "Carcinoma", "Cancer", "Metastasis"}
    positive_words = {"Benign", "Normal findings", "Negative result"}

    prev_severity = sum(1 for k in prev_keywords if k in danger_words)
    curr_severity = sum(1 for k in current_keywords if k in danger_words)

    if curr_severity < prev_severity:
        lines.append("📈 <b>Overall trend:</b> Improvement — fewer concerning markers than last report.")
    elif curr_severity > prev_severity:
        lines.append("📉 <b>Overall trend:</b> Worsening — more concerning markers. Please consult your doctor.")
    else:
        lines.append("➡️ <b>Overall trend:</b> No significant change from last report.")

    return "<br>".join(lines)


@app.route("/analyze-report", methods=["POST"])
def analyze_report():

    if "report" not in request.files:
        return jsonify({"summary": "No file uploaded", "text": ""})

    file = request.files["report"]

    if file.filename == "":
        return jsonify({"summary": "No file selected", "text": ""})

    allowed = ["png", "jpg", "jpeg"]
    ext = file.filename.split(".")[-1].lower()

    if ext not in allowed:
        return jsonify({
            "summary": "Please upload a PNG or JPG image",
            "text": ""
        })

    path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(path)

    try:
        text = ocr_extract_text(path)

    except Exception as e:
        print(f"OCR failed for '{path}': {e}")
        return jsonify({
            "summary": f"Unable to read the report. ({e})",
            "text": ""
        })

    text_lower = text.lower()
    result, severity = classify_report(text_lower)
    keywords = extract_keywords(text_lower)

    # ── Save to history ──
    email = session.get("email")
    comparison = None
    history_list = []

    if email:
        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()

        # Fetch previous reports for comparison (newest first)
        cursor.execute("""
            SELECT id, email, filename, summary, keywords, created_at
            FROM report_history
            WHERE email=?
            ORDER BY created_at DESC
        """, (email,))
        history_rows = cursor.fetchall()

        comparison = build_comparison(keywords, history_rows)

        # Save current report
        cursor.execute("""
            INSERT INTO report_history (email, filename, extracted_text, summary, keywords, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            email,
            file.filename,
            text[:2000],
            result,
            ", ".join(keywords),
            datetime.now().isoformat(sep=" ", timespec="seconds")
        ))
        conn.commit()

        # Re-fetch to include the just-saved one
        cursor.execute("""
            SELECT id, filename, summary, keywords, created_at
            FROM report_history
            WHERE email=?
            ORDER BY created_at DESC
            LIMIT 10
        """, (email,))
        for row in cursor.fetchall():
            history_list.append({
                "id": row[0],
                "filename": row[1],
                "summary": row[2],
                "keywords": row[3],
                "date": row[4][:16]
            })

        conn.close()

    return jsonify({
        "text": text[:800],
        "summary": result,
        "severity": severity,
        "keywords": keywords,
        "comparison": comparison,
        "history": history_list
    })


@app.route("/report-history")
def report_history_api():
    """Return the logged-in user's full report history as JSON."""
    email = session.get("email")
    if not email:
        return jsonify([])

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, filename, summary, keywords, created_at
        FROM report_history
        WHERE email=?
        ORDER BY created_at DESC
        LIMIT 10
    """, (email,))
    rows = cursor.fetchall()
    conn.close()

    return jsonify([{
        "id": r[0],
        "filename": r[1],
        "summary": r[2],
        "keywords": r[3],
        "date": r[4][:16]
    } for r in rows])


# ---------------- RUN APP ---------------- #

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)