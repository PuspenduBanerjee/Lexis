"""Auth stub + RBAC dependencies.

`get_current_user` is the single seam meant to be swapped for real auth later —
every route depends on it by signature only, never inspects headers directly.
"""

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from lexis_api.config import settings
from lexis_api.db import get_db
from lexis_api.models import Connection, Role, SemanticModelRecord, User


def find_user_or_401(db: Session, user_id: int) -> User:
    """Plain (non-`Depends`) lookup, so callers outside FastAPI's dependency
    injection - e.g. the MCP mount in `routers/mcp.py`, which drives raw ASGI and
    can't use `Depends` - can still reuse the same auth check."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail=f"Unknown user id {user_id}")
    return user


def get_current_user(
    x_user_id: int | None = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
) -> User:
    uid = x_user_id if x_user_id is not None else settings.default_user_id
    return find_user_or_401(db, uid)


def require_roles(*roles: Role):
    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"role {user.role.value!r} not permitted")
        return user

    return _check


require_admin = require_roles(Role.ADMIN)
require_editor_or_admin = require_roles(Role.ADMIN, Role.EDITOR)


def get_owned_or_admin_model(
    model_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SemanticModelRecord:
    record = db.get(SemanticModelRecord, model_id)
    if record is None:
        raise HTTPException(status_code=404, detail="model not found")
    if user.role != Role.ADMIN and record.owner_id != user.id:
        raise HTTPException(status_code=403, detail="not the owner of this model")
    return record


def find_model_or_404(db: Session, model_id: int) -> SemanticModelRecord:
    record = db.get(SemanticModelRecord, model_id)
    if record is None:
        raise HTTPException(status_code=404, detail="model not found")
    return record


def get_visible_model(
    model_id: int,
    user: User = Depends(get_current_user),  # noqa: ARG001 - enforces a resolvable user
    db: Session = Depends(get_db),
) -> SemanticModelRecord:
    """Any authenticated user can view/transpile/run any model (no sharing/ACL system)."""
    return find_model_or_404(db, model_id)


def get_owned_or_admin_connection(
    connection_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Connection:
    record = db.get(Connection, connection_id)
    if record is None:
        raise HTTPException(status_code=404, detail="connection not found")
    if user.role != Role.ADMIN and record.owner_id != user.id:
        raise HTTPException(status_code=403, detail="not the owner of this connection")
    return record


def find_connection_or_404(db: Session, connection_id: int) -> Connection:
    record = db.get(Connection, connection_id)
    if record is None:
        raise HTTPException(status_code=404, detail="connection not found")
    return record


def get_visible_connection(
    connection_id: int,
    user: User = Depends(get_current_user),  # noqa: ARG001 - enforces a resolvable user
    db: Session = Depends(get_db),
) -> Connection:
    """Any authenticated user can view/run against any connection (same
    workspace-wide visibility as models - no sharing/ACL system)."""
    return find_connection_or_404(db, connection_id)
