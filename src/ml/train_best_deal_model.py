import sqlite3
import pandas as pd
import joblib

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report


DB_PATH = "data/prices.db"
MODEL_PATH = "src/ml/best_deal_model.pkl"


def load_data():
    conn = sqlite3.connect(DB_PATH)

    query = """
    SELECT
        platform,
        product_name,
        price,
        mrp,
        discount_pct,
        price_per_unit,
        delivery_mins,
        savings,
        is_best_deal
    FROM prices
    WHERE price IS NOT NULL
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    return df


def train_model():
    df = load_data()

    if df.empty:
        print("No data found. First run the Streamlit app and search products.")
        return

    df = df.fillna(0)

    X = df[
        [
            "platform",
            "product_name",
            "price",
            "mrp",
            "discount_pct",
            "price_per_unit",
            "delivery_mins",
            "savings",
        ]
    ]

    y = df["is_best_deal"]

    categorical_features = ["platform", "product_name"]

    numeric_features = [
        "price",
        "mrp",
        "discount_pct",
        "price_per_unit",
        "delivery_mins",
        "savings",
    ]

    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), categorical_features),
            ("num", "passthrough", numeric_features),
        ]
    )

    model = RandomForestClassifier(
        n_estimators=100,
        random_state=42,
        class_weight="balanced"
    )

    pipeline = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("model", model),
        ]
    )

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42
    )

    pipeline.fit(X_train, y_train)

    y_pred = pipeline.predict(X_test)

    print("Accuracy:", accuracy_score(y_test, y_pred))
    print(classification_report(y_test, y_pred))

    joblib.dump(pipeline, MODEL_PATH)
    print("Model saved:", MODEL_PATH)


if __name__ == "__main__":
    train_model()
