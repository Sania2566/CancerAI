import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.ensemble import RandomForestClassifier
import pickle

# Load dataset
df = pd.read_csv("cancer_dataset.csv")

# Select useful columns
df = df[[
"Age",
"Gender",
"Smoking_Status",
"Weight",
"Height",
"Cancer_Type"
]]

# Encode categorical
le_gender = LabelEncoder()
le_smoke = LabelEncoder()
le_cancer = LabelEncoder()

df["Gender"] = le_gender.fit_transform(df["Gender"])
df["Smoking_Status"] = le_smoke.fit_transform(df["Smoking_Status"])
df["Cancer_Type"] = le_cancer.fit_transform(df["Cancer_Type"])

# Features and label
X = df.drop("Cancer_Type", axis=1)
y = df["Cancer_Type"]

# Split
X_train, X_test, y_train, y_test = train_test_split(X,y,test_size=0.2)

# Train model
model = RandomForestClassifier()
model.fit(X_train,y_train)

# Save model
pickle.dump(model,open("model.pkl","wb"))
pickle.dump(le_gender,open("gender.pkl","wb"))
pickle.dump(le_smoke,open("smoke.pkl","wb"))
pickle.dump(le_cancer,open("cancer.pkl","wb"))

print("Model trained successfully")