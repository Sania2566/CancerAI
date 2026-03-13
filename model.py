import pandas as pd
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
import pickle

# Load dataset
df = pd.read_csv("cancer_dataset.csv")

# Select useful columns
df = df[["Age","Gender","Smoking_Status","Cancer_Type"]]

# Encode text columns
le_gender = LabelEncoder()
le_smoking = LabelEncoder()
le_cancer = LabelEncoder()

df["Gender"] = le_gender.fit_transform(df["Gender"])
df["Smoking_Status"] = le_smoking.fit_transform(df["Smoking_Status"])
df["Cancer_Type"] = le_cancer.fit_transform(df["Cancer_Type"])

X = df[["Age","Gender","Smoking_Status"]]
y = df["Cancer_Type"]

# Split dataset
X_train, X_test, y_train, y_test = train_test_split(X,y,test_size=0.2)

# Train model
model = RandomForestClassifier()
model.fit(X_train,y_train)

# Save model
pickle.dump(model,open("cancer_model.pkl","wb"))

print("Model trained successfully")