"""add users.email

Revision ID: 615b26d0daa3
Revises: 25948f80e4d6
Create Date: 2026-09-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '615b26d0daa3'
down_revision: Union[str, Sequence[str], None] = '25948f80e4d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable: the 3 seeded dev-stub users (admin/editor1/viewer1) have no email -
    # only users auto-provisioned via Google sign-in get one (see deps.py).
    op.add_column('users', sa.Column('email', sa.String(), nullable=True))
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_column('users', 'email')
