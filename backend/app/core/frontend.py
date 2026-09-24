"""Serving the built frontend from the API process.

In production the page and the API share one origin. That keeps the visitor
cookie first-party — a frontend on another site would need SameSite=None
cookies, which browsers increasingly refuse — and it means one container to
deploy instead of two.

Only switched on when STATIC_DIR is set; in development Vite serves the page.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles


class _FingerprintedAssets(StaticFiles):
    """Vite puts a content hash in every file name under /assets, so a file
    at a given URL never changes and can be cached for good."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def mount_frontend(app: FastAPI, directory: str | Path) -> None:
    """Serve `directory` (a Vite build) at `/`, with SPA fallback.

    Must be called after the API routers are included, so the catch-all
    route never shadows an API path.
    """
    root = Path(directory).resolve()
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(
            f"STATIC_DIR={directory} holds no index.html. "
            "Build the frontend first (npm run build in frontend/)."
        )

    if (root / "assets").is_dir():
        app.mount("/assets", _FingerprintedAssets(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def single_page_app(path: str):
        # An unknown API path is a 404, not the app shell.
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")

        # Real files at the top of the build (favicon.svg). Resolved and
        # checked so no path can reach outside the build directory.
        if path:
            candidate = (root / path).resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                return FileResponse(candidate)

        # Every other path is a client-side route: hand over the shell and
        # let React Router take it from there. Never cached, so a deploy is
        # picked up on the next visit.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
