
import os
import joblib
import pandas as pd


MODEL_PATH = "src/ml/best_deal_model.pkl"


def model_exists():
    return os.path.exists(MODEL_PATH)


def predict_best_deal(product):
    model = joblib.load(MODEL_PATH)

    input_df = pd.DataFrame([product])

    prediction = model.predict(input_df)[0]
    probability = model.predict_proba(input_df)[0].max()

    return {
        "prediction": int(prediction),
        "confidence": round(float(probability) * 100, 2)
    }
