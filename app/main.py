from fastapi import FastAPI


app = FastAPI(
    title="BB Massoterapia AI",
    description="API REST do MVP BB Massoterapia AI, preparada para deploy em nuvem.",
    version="0.1.0",
)


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "API BB Massoterapia AI funcionando"}


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}

