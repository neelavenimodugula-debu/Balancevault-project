from fastapi import FastAPI

app = FastAPI(title="LedgerLine", version="0.1.0")


@app.get("/health", tags=["operations"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}