"""statuses: «مرفوض / Rejected» is renamed «زائف / False report»

Data only (no schema change). The status code stays `rejected`; reports in this status are now shown to
staff accounts only (ReportStatus.STAFF_ONLY). Portable (MariaDB and SQLite).

Revision ID: e7b3f9a2c6d1
Revises: c5e8a1d4b7f2
Create Date: 2026-11-26 14:00:00

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'e7b3f9a2c6d1'
down_revision = 'c5e8a1d4b7f2'
branch_labels = None
depends_on = None

_SQL = sa.text(
    "UPDATE report_status_translations SET name = :name WHERE locale = :locale "
    "AND status_id IN (SELECT id FROM report_statuses WHERE code = 'rejected')"
)


def _rename(ar, en):
    op.execute(_SQL.bindparams(name=ar, locale="ar"))
    op.execute(_SQL.bindparams(name=en, locale="en"))


def upgrade():
    _rename("زائف", "False report")


def downgrade():
    _rename("مرفوض", "Rejected")
