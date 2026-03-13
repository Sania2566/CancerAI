from flask import Flask, render_template, request, jsonify
import pandas as pd
from geopy.distance import geodesic
import pickle
import sqlite3
import pytesseract
from PIL import Image
import os
from flask import Flask, render_template, request, jsonify, redirect, session
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

app = Flask(__name__)
app.secret_key = "secret123"

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
    cancer_stage TEXT
)
""")

    conn.commit()
    conn.close()

init_db()

# ---------------- LOAD DATA ---------------- #

hospitals_df = pd.read_csv("data/hospitals.csv")
df = pd.read_csv("data/cancer_dataset.csv")

model = pickle.load(open("cancer_model.pkl", "rb"))

# ---------------- HOME ---------------- #

@app.route("/")
def home():
    return render_template("signup.html")


# ---------------- SIGNUP ---------------- #

@app.route("/signup", methods=["POST"])
def signup():

    name = request.form["name"]
    email = request.form["email"]
    password = request.form["password"]

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO users (name,email,password) VALUES (?,?,?)",
            (name, email, password)
        )

        conn.commit()
        conn.close()

        return render_template("signup.html", show_login=True)

    except sqlite3.IntegrityError:

        conn.close()

        return render_template("signup.html", show_signup=True)


# ---------------- LOGIN ---------------- #

@app.route("/login", methods=["POST"])
def login():

    email = request.form["email"]
    password = request.form["password"]

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM users WHERE email=? AND password=?",
        (email, password)
    )

    user = cursor.fetchone()

    if user:

        session["email"] = email

        cursor.execute(
            "SELECT * FROM profiles WHERE email=?",
            (email,)
        )

        profile = cursor.fetchone()

        conn.close()

        if profile:
            return redirect("/analysis")
        else:
            return redirect("/profile_setup")

    conn.close()

    return render_template("signup.html", show_login=True)

@app.route("/profile_setup")
def profile_setup():

    email = session.get("email")

    return render_template("profile_setup.html", email=email)

@app.route("/save_profile", methods=["POST"])
def save_profile():

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

    return redirect("/profile")

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
    return render_template("index.html")


@app.route("/analyze_symptoms", methods=["POST"])
def analyze_symptoms():

    data = request.get_json()

    risk = 0

    if data.get("age") == "Above 60":
        risk += 15
    elif data.get("age") == "45-60":
        risk += 10

    if data.get("smoking") == "Regularly":
        risk += 20
    elif data.get("smoking") == "Occasionally":
        risk += 10

    if data.get("weight_loss") == "Significant":
        risk += 20
    elif data.get("weight_loss") == "Slight":
        risk += 10

    if data.get("cough") == "More than 3 weeks":
        risk += 15
    elif data.get("cough") == "Few days":
        risk += 5

    if data.get("fatigue") == "Often":
        risk += 10
    elif data.get("fatigue") == "Sometimes":
        risk += 5

    # RESULT
    if risk < 25:
        severity = "Low"
        condition = "Likely minor health issue"
        advice = "Maintain a healthy lifestyle and monitor symptoms."

    elif risk < 50:
        severity = "Moderate"
        condition = "Some concerning symptoms"
        advice = "Consider consulting a doctor if symptoms persist."

    else:
        severity = "High"
        condition = "Multiple concerning symptoms"
        advice = "It is recommended to consult a doctor."

    return jsonify({
        "risk": risk,
        "severity": severity,
        "condition": condition,
        "advice": advice
    })

# ---------------- DASHBOARD ---------------- #

df["Diagnosis_Date"] = pd.to_datetime(df["Diagnosis_Date"], errors="coerce")
df["Year"] = df["Diagnosis_Date"].dt.year


@app.route("/dashboard")
def dashboard():

    cancer_counts = df["Cancer_Type"].value_counts()
    smoking_counts = df["Smoking_Status"].value_counts()
    treatment_counts = df["Treatment_Type"].value_counts()
    yearly_cases = df.groupby("Year").size()

    return render_template(
        "dashboard.html",

        cancer_labels=list(cancer_counts.index),
        cancer_values=[int(x) for x in cancer_counts.values],

        smoking_labels=list(smoking_counts.index),
        smoking_values=[int(x) for x in smoking_counts.values],

        treatment_labels=list(treatment_counts.index),
        treatment_values=[int(x) for x in treatment_counts.values],

        year_labels=[int(x) for x in yearly_cases.index],
        year_values=[int(x) for x in yearly_cases.values]
    )


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


@app.route("/analyze-report", methods=["POST"])
def analyze_report():

    if "report" not in request.files:
        return jsonify({"summary": "No file uploaded", "text": ""})

    file = request.files["report"]

    if file.filename == "":
        return jsonify({"summary": "No file selected", "text": ""})

    path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(path)
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
        img = Image.open(path).convert("L")  # convert to grayscale
        text = pytesseract.image_to_string(img)

    except:
        return jsonify({
            "summary": "Unable to read the report. Please upload an image file.",
            "text": ""
        })

    text_lower = text.lower()

    # AI style interpretation
    if "malignant" in text_lower or "carcinoma" in text_lower or "cancer" in text_lower:
        result = "⚠️ Report indicates possible malignant or cancer-related findings. Please consult an oncologist."

    elif "benign" in text_lower:
        result = "✅ Report suggests benign (non-cancerous) findings."

    elif "tumor" in text_lower:
        result = "⚠️ Tumor mentioned in report. Medical evaluation recommended."

    else:
        result = "❗ No clear diagnosis detected from report text."

    return jsonify({
        "text": text[:800],
        "summary": result
    })


# ---------------- RUN APP ---------------- #

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)




