from __future__ import annotations

from apps.api.app import create_app

app = create_app()
# app.state.repository and app.state.workflow are configured by create_app().


def repository():
    return app.state.repository


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("apps.api.main:app", host="0.0.0.0", port=8000)
