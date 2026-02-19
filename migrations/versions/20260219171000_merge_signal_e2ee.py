"""Merge signal_e2ee_001 and 34ff77d753f8 branches

Revision ID: merge_signal_e2ee
Revises: signal_e2ee_001, 34ff77d753f8
Create Date: 2026-02-19 17:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'merge_signal_e2ee'
down_revision = ('signal_e2ee_001', '34ff77d753f8')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
