"""driving mode: composite index on reports (latitude, longitude)

Speeds up the bounding-box pre-filter of GET /api/v1/reports/nearby.
Portable (MariaDB and SQLite); no data change.

Revision ID: a3d9c2e41f07
Revises: 6818f5288d1c
Create Date: 2026-11-24 12:00:00

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a3d9c2e41f07'
down_revision = '6818f5288d1c'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.create_index('ix_reports_lat_lng', ['latitude', 'longitude'], unique=False)


def downgrade():
    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.drop_index('ix_reports_lat_lng')
