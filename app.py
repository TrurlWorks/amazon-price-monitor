"""Local-AI-Lab entrypoint; Compose starts the ASGI factory directly."""

import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "backend.main:create_app",
        factory=True,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8543")),
    )
