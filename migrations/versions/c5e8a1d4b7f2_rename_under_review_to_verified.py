"""statuses: «قيد المراجعة / Under review» is renamed «متحقق منه / Verified»

Data only (no schema change). The status code stays `under_review`, so the workflow, the driving-mode
settings and existing reports are unaffected; only the displayed names change. Reports submitted by
staff accounts are moved to this status automatically (app/services/reports.py:create_report).
Portable (MariaDB and SQLite).

Revision ID: c5e8a1d4b7f2
Revises: a3d9c2e41f07
Create Date: 2026-11-26 12:00:00

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'c5e8a1d4b7f2'
down_revision = 'a3d9c2e41f07'
branch_labels = None
depends_on = None

_SQL = sa.text(
    "UPDATE report_status_translations SET name = :name WHERE locale = :locale "
    "AND status_id IN (SELECT id FROM report_statuses WHERE code = 'under_review')"
)


def _rename(ar, en):
    op.execute(_SQL.bindparams(name=ar, locale="ar"))
    op.execute(_SQL.bindparams(name=en, locale="en"))


def upgrade():
    _rename("متحقق منه", "Verified")


def downgrade():
    _rename("قيد المراجعة", "Under review")
