"""Google auth (via a trusted edge/tunnel) + dev stub + RBAC dependencies.

`get_current_user` is the single seam every route depends on by signature only,
never inspecting headers directly - see it for how the auth paths are ordered.
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


def find_or_create_google_user(db: Session, email: str, display_name: str | None) -> User:
    """Look up (or, on first sign-in, auto-provision as `Role.VIEWER`) the user for a
    Google-authenticated identity. `email` is trusted here purely because it arrived
    as one of the headers a tunnel's edge auth injects - `X-User-Email` (ngrok's
    `oauth` traffic-policy action) or `Cf-Access-Authenticated-User-Email` (Cloudflare
    Access in front of a `cloudflared` tunnel) - see `get_current_user`. Both tunnel
    providers strip any client-supplied copy of their own header before adding the
    verified one, so this is only safe when the app itself isn't otherwise directly
    reachable (no port published alongside the tunnel) - never wire a client-facing
    deployment to accept either header straight from a browser. An admin can promote
    the new user's role afterward like any other.
    """
    user = db.query(User).filter(User.email == email).first()
    if user is not None:
        return user

    # `username` is unique; a Google display name (or the email, as fallback) can
    # collide with a seeded dev user or an earlier Google sign-in, so disambiguate.
    base_username = display_name or email
    username = base_username
    suffix = 1
    while db.query(User).filter(User.username == username).first() is not None:
        suffix += 1
        username = f"{base_username} ({suffix})"

    user = User(username=username, email=email, role=Role.VIEWER)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_current_user(
    x_user_email: str | None = Header(default=None, alias="X-User-Email"),
    x_user_name: str | None = Header(default=None, alias="X-User-Name"),
    cf_access_email: str | None = Header(default=None, alias="Cf-Access-Authenticated-User-Email"),
    x_account_id: int | None = Header(default=None, alias="X-Account-Id"),
    db: Session = Depends(get_db),
) -> User:
    # Google identity always wins when present, regardless of `dev_auth_header_enabled` -
    # it's the real, tunnel-verified signal; the account-id header below is just a stub.
    # `x_user_email` (ngrok) is checked first only as an arbitrary tie-break - a
    # deployment realistically sits behind exactly one tunnel, so both are never set
    # on the same request. Cloudflare Access has no equivalent "display name" header,
    # so `display_name` stays None (falls back to the email as the username) for it.
    google_email = x_user_email or cf_access_email
    if google_email:
        display_name = x_user_name if x_user_email else None
        return find_or_create_google_user(db, email=google_email, display_name=display_name)
    if not settings.dev_auth_header_enabled:
        raise HTTPException(status_code=401, detail="authentication required")
    uid = x_account_id if x_account_id is not None else settings.default_user_id
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
