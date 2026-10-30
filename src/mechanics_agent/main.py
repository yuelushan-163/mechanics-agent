from __future__ import annotations

import uvicorn

from mechanics_agent.config import Settings


def run() -> None:
    settings = Settings.from_env()
    uvicorn.run(
        "mechanics_agent.api:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )


if __name__ == "__main__":
    run()

