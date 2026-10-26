"""Standalone entry point for running TVT MOBILE without the TestPilot dashboard."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from ShopDemo import router

app = FastAPI(title="TVT MOBILE Demo Shop")
app.include_router(router)
app.mount(
    "/shop-assets",
    StaticFiles(directory=Path(__file__).resolve().parent / "static"),
    name="shop-assets",
)


@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse(url="/shop")
