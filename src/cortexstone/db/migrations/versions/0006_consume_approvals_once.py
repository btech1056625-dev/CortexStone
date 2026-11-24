"""Make approved action evidence single-use.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_approvals_status_valid", "approvals", type_="check")
    op.create_check_constraint(
        "status_valid",
        "approvals",
        "status IN ('pending', 'approved', 'rejected', 'expired', 'revoked', 'consumed')",
    )


def downgrade() -> None:
    op.execute(sa.text("UPDATE approvals SET status = 'expired' WHERE status = 'consumed'"))
    op.drop_constraint("ck_approvals_status_valid", "approvals", type_="check")
    op.create_check_constraint(
        "status_valid",
        "approvals",
        "status IN ('pending', 'approved', 'rejected', 'expired', 'revoked')",
    )
