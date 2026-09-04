"""User listing (admin only) and "who am I" (any authenticated user)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from lexis_api.db import get_db
from lexis_api.deps import get_current_user, require_admin
from lexis_api.models import User
from lexis_api.schemas import UserOut

router = APIRouter(prefix="/api/users", tags=["users"])


def _to_out(user: User) -> UserOut:
    return UserOut(id=user.id, username=user.username, role=user.role.value)


@router.get("", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),  # noqa: ARG001
) -> list[UserOut]:
    return [_to_out(u) for u in db.query(User).order_by(User.id).all()]


@router.get("/me", response_model=UserOut)
def get_me(user: User = Depends(get_current_user)) -> UserOut:
    return _to_out(user)
