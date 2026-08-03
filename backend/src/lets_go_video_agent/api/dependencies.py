from typing import cast

from fastapi import Request

from lets_go_video_agent.bootstrap import Container


def get_container(request: Request) -> Container:
    return cast(Container, request.app.state.container)
