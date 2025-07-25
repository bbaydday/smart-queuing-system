

import pandas as pd
import glob
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
import joblib

# CSV ဖိုင်အားလုံး load
csv_files = glob.glob("daily_logs/*.csv")
df_list = [pd.read_csv(file) for file in csv_files]
df = pd.concat(df_list, ignore_index=True)

# Features & Target
X = df[['age', 'gender', 'patient_type']]
y = df['service_time']

# Categorical columns
categorical_features = ['gender', 'patient_type']

# Preprocessing + Model Pipeline
preprocessor = ColumnTransformer(
    transformers=[
        ('cat', OneHotEncoder(handle_unknown='ignore'), categorical_features)
    ],
    remainder='passthrough'
)

model = Pipeline(steps=[
    ('preprocessor', preprocessor),
    ('regressor', LinearRegression())
])

# Train
model.fit(X, y)

# Save

joblib.dump(model, "linear_service_time3_model.pkl")
print("✅ Model trained and saved as linear_service_time3_model.pkl")
