from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from lets_go_video_agent import __version__
from lets_go_video_agent.api.router import router
from lets_go_video_agent.application.errors import ApplicationError
from lets_go_video_agent.bootstrap import Container, build_container
from lets_go_video_agent.config import Settings, get_settings


def create_app(
    *,
    settings: Settings | None = None,
    container: Container | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_container = container or build_container(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = resolved_container
        await resolved_container.startup()
        try:
            yield
        finally:
            await resolved_container.shutdown()

    app = FastAPI(
        title="LetsGoVideoAgent API",
        summary="Evidence-first general video understanding agent",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.container = resolved_container
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api/v1")

    @app.exception_handler(ApplicationError)
    async def handle_application_error(
        _request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            media_type="application/problem+json",
            content={
                "type": f"https://letsgovideoagent.dev/problems/{exc.code}",
                "title": "请求无法完成",
                "status": exc.status_code,
                "detail": str(exc),
                "code": exc.code,
            },
        )

    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "lets_go_video_agent.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_env == "development",
    )


if __name__ == "__main__":
    run()
