"""FastAPI application entry point for the conference scanner."""

import logging
import os

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

app = FastAPI(
    title="Conference Exhibitor Scanner",
    description="Scrape conference exhibitor lists, enrich and score against your ICP",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


def run():
    """Entry point for the `conference-scanner` CLI command."""
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=port,
        reload=os.getenv("ENV", "") == "dev",
    )


if __name__ == "__main__":
    run()
