"""FastAPI app: CORS, exception handlers, router registration, startup seed."""

from contextlib import asynccontextmanager

import duckdb
import snowflake.connector
import yaml
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from semantica_api.config import settings
from semantica_api.db import Base, SessionLocal, engine
from semantica_api.routers import connections, duckdb_run, graph, models, transpile, users
from semantica_api.routers.mcp import mcp_asgi_app
from semantica_api.seed import seed_default_users, seed_sample_model


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_default_users(db)
        seed_sample_model(db)
    finally:
        db.close()
    yield


app = FastAPI(title="Semantica API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ValidationError)
def handle_osi_validation_error(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(yaml.YAMLError)
def handle_yaml_syntax_error(request: Request, exc: yaml.YAMLError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": f"invalid YAML: {exc}"})


@app.exception_handler(ValueError)
def handle_library_value_error(request: Request, exc: ValueError) -> JSONResponse:
    # Covers semantica.resolved_model.UnresolvedJoinError/MissingExpressionError
    # (both subclass ValueError) and plain ValueError from the emitters/dispatch.
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(duckdb.Error)
def handle_duckdb_error(request: Request, exc: duckdb.Error) -> JSONResponse:
    # An uploaded .duckdb file that doesn't actually match the model's declared
    # dataset sources (wrong schema/table names) raises here - a 400, not a 500,
    # since it's a bad-input condition (mismatched file), not a server fault.
    return JSONResponse(
        status_code=400,
        content={"detail": f"query failed against the provided database: {exc}"},
    )


@app.exception_handler(snowflake.connector.errors.Error)
def handle_snowflake_error(request: Request, exc: snowflake.connector.errors.Error) -> JSONResponse:
    # Covers query-execution failures (e.g. the model's `source` doesn't match a
    # real table in the connected Snowflake account) that aren't already caught
    # and wrapped at connect time by connection_runtime.open_snowflake_connection.
    return JSONResponse(
        status_code=400,
        content={"detail": f"query failed against Snowflake: {exc}"},
    )


app.include_router(models.router)
app.include_router(transpile.router)
app.include_router(duckdb_run.router)
app.include_router(duckdb_run.demo_router)
app.include_router(graph.router)
app.include_router(users.router)
app.include_router(connections.router)

# Mounted (not `include_router`'d) after every other `/api/models/...` route, so
# Starlette's first-match-wins routing always tries those more specific routes
# before falling through to this prefix mount - see `routers/mcp.py` for why the
# live MCP endpoint needs a raw ASGI mount instead of a normal FastAPI route.
app.mount("/api/models", mcp_asgi_app)
