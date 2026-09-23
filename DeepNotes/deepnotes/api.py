"""Local HTTP boundary. Run with one process and bind to loopback only."""
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from fastapi import FastAPI, Request, Query
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import ROOT, Settings
from .contracts import EntryIn, GuidanceIn, QueryIn, RollbackIn
from .models import CloudModel, DemoModel, ModelUnavailable, public_error
from .pipelines import Pipelines
from .storage import Store
from .worker import Worker


def create_app(settings=None, model=None, start_worker=True):
    settings = settings or Settings.from_env()
    store = Store(settings.db_path)
    model = model or (DemoModel() if settings.demo_mode else CloudModel(settings))
    pipelines = Pipelines(store, model)
    worker = Worker(store, pipelines, settings)

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        if start_worker:
            worker.start()
        try:
            yield
        finally:
            if start_worker:
                worker.stop()

    app = FastAPI(title="DeepNotes", version="0.1.0", lifespan=lifespan)
    app.state.store, app.state.pipelines, app.state.worker = store, pipelines, worker
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            # Same-origin JSON application, not an unauthenticated cross-site API.
            if origin:
                parsed = urlparse(origin)
                if parsed.netloc != request.headers.get("host") or parsed.scheme not in ("http", "https"):
                    return JSONResponse({"detail": "Cross-origin requests are not allowed"}, status_code=403)
            if not request.headers.get("content-type", "").startswith("application/json"):
                return JSONResponse({"detail": "Use application/json"}, status_code=415)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        details = [".".join(str(part) for part in error["loc"]) + ": " + error["msg"] for error in exc.errors()[:5]]
        return JSONResponse({"detail": "; ".join(details)}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_failure(request, exc):
        return JSONResponse({"detail": public_error(exc)}, status_code=500)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"detail": str(exc).strip("'")}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": public_error(exc)}, status_code=400)

    @app.exception_handler(ModelUnavailable)
    async def model_unavailable(request, exc):
        return JSONResponse({"detail": public_error(exc)}, status_code=503)

    @app.post("/api/entries", status_code=201)
    def create_entry(payload: EntryIn):
        result = store.create_entry(**payload.model_dump())
        worker.notify()
        return result

    @app.get("/api/entries")
    def entries(limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)):
        return {"items": store.entries(limit, offset)}

    @app.post("/api/guidance", status_code=201)
    def guidance(payload: GuidanceIn):
        result = store.add_guidance(**payload.model_dump())
        worker.notify()
        return {"id": result}

    @app.get("/api/guidance")
    def list_guidance():
        return {"items": store.guidance()}

    @app.post("/api/queries")
    def answer(payload: QueryIn):
        return pipelines.answer(payload.question)

    @app.get("/api/interactions")
    def interactions(q: str = Query("", max_length=4000), limit: int = Query(20, ge=1, le=100)):
        return {"items": store.interactions(q, limit)}

    @app.get("/api/status")
    def status():
        return {**store.status(), "model_configured": model.configured, "demo_mode": settings.demo_mode,
                "worker_running": worker.running, "last_worker_error": worker.last_error}

    @app.get("/api/jobs")
    def jobs(limit: int = Query(30, ge=1, le=100)):
        return {"items": store.jobs(limit)}

    @app.post("/api/jobs/{job_id}/retry")
    def retry(job_id: int):
        result = store.retry_job(job_id)
        worker.notify()
        return {"job_id": result}

    @app.get("/api/structure")
    def structure():
        return store.catalog()

    @app.post("/api/structure/reorganize")
    def reorganize():
        result = store.queue_structure()
        worker.notify()
        return {"job_id": result}

    @app.post("/api/structure/rollback")
    def rollback(payload: RollbackIn):
        result = pipelines.rollback(payload.version_id)
        worker.notify()
        return {"version": result}

    app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="ui")
    return app
