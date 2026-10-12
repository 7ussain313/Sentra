from fastapi import FastAPI

app = FastAPI(title="Sentra Agent Service")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
