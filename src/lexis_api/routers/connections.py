"""CRUD for named, reusable datasource connections (duckdb_file, snowflake) - see
`connection_runtime.py` for the execution side and `models.py::Connection` for why
secrets are never persisted directly."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lexis_api.connection_runtime import test_connection as run_connection_test
from lexis_api.connection_runtime import validate_connection_config
from lexis_api.db import get_db
from lexis_api.deps import get_current_user, get_owned_or_admin_connection, get_visible_connection, require_editor_or_admin
from lexis_api.models import Connection, ConnectionType, User
from lexis_api.schemas import ConnectionIn, ConnectionOut, ConnectionTestOut, to_connection_out

router = APIRouter(prefix="/api/connections", tags=["connections"])


@router.get("", response_model=list[ConnectionOut])
def list_connections(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),  # noqa: ARG001 - requires a resolvable user
) -> list[ConnectionOut]:
    records = db.query(Connection).order_by(Connection.id).all()
    return [to_connection_out(r) for r in records]


@router.post("", response_model=ConnectionOut, status_code=201)
def create_connection(
    body: ConnectionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_editor_or_admin),
) -> ConnectionOut:
    conn_type = ConnectionType(body.type)
    validate_connection_config(conn_type, body.config)

    record = Connection(name=body.name, type=conn_type, owner_id=user.id, config=body.config)
    db.add(record)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"a connection named {body.name!r} already exists") from exc
    db.refresh(record)
    return to_connection_out(record)


@router.get("/{connection_id}", response_model=ConnectionOut)
def get_connection(record: Connection = Depends(get_visible_connection)) -> ConnectionOut:
    return to_connection_out(record)


@router.put("/{connection_id}", response_model=ConnectionOut)
def update_connection(
    body: ConnectionIn,
    db: Session = Depends(get_db),
    record: Connection = Depends(get_owned_or_admin_connection),
) -> ConnectionOut:
    conn_type = ConnectionType(body.type)
    validate_connection_config(conn_type, body.config)

    record.name = body.name
    record.type = conn_type
    record.config = body.config
    db.add(record)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"a connection named {body.name!r} already exists") from exc
    db.refresh(record)
    return to_connection_out(record)


@router.delete("/{connection_id}", status_code=204)
def delete_connection(
    db: Session = Depends(get_db),
    record: Connection = Depends(get_owned_or_admin_connection),
) -> None:
    db.delete(record)
    db.commit()


@router.post("/{connection_id}/test", response_model=ConnectionTestOut)
def test_connection_endpoint(record: Connection = Depends(get_visible_connection)) -> ConnectionTestOut:
    return ConnectionTestOut(**run_connection_test(record))
