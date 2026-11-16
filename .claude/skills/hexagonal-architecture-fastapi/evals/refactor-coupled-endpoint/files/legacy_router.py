# Prototipo de vaaet-app: un solo archivo con todo el flujo de análisis.
import os
import tempfile

import joblib
import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile
from keras.models import load_model
from sqlalchemy import create_engine, text

from vaaet.vision.analysis import analyze_video

router = APIRouter()

ENGINE = create_engine(os.environ["DATABASE_URL"])
MODEL = load_model("/models/current/model.keras")
SCALER = joblib.load("/models/current/scaler.joblib")


def classify(df: pd.DataFrame) -> pd.DataFrame:
    probs = MODEL.predict(SCALER.transform(df.iloc[:, :19]))
    df["state"] = probs.argmax(axis=1)
    # Si hay muchos vehículos detenidos asumimos accidente.
    df.loc[df["stopped_ratio"] > 0.8, "state"] = 3
    return df


@router.post("/analyze")
async def analyze(video: UploadFile = File(...), camera: str = "default"):
    if not video.filename.endswith(".mp4"):
        raise HTTPException(400, "solo mp4")
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.write(await video.read())
    tmp.close()
    try:
        result = analyze_video(tmp.name)
    except Exception as exc:
        raise HTTPException(500, f"fallo el analisis: {exc}")
    df = classify(result.telemetry)
    with ENGINE.begin() as conn:
        for _, row in df.iterrows():
            conn.execute(
                text("INSERT INTO telemetry (camera, minute, state) VALUES (:c, :m, :s)"),
                {"c": camera, "m": row["minute"], "s": int(row["state"])},
            )
    return {"camera": camera, "minutes": df.to_dict(orient="records")}


@router.get("/analyses/{camera}")
async def history(camera: str):
    with ENGINE.connect() as conn:
        rows = conn.execute(text(f"SELECT * FROM telemetry WHERE camera = '{camera}'")).fetchall()
    if not rows:
        raise HTTPException(404, "sin datos")
    return [dict(r._mapping) for r in rows]
