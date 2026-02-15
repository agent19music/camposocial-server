"""Add engagement_multiplier to users

Revision ID: 20260209201724_5463ea4b
Revises: cccf36f07905
Create Date: 2026-02-09 20:17:24.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260209201724_5463ea4b'
down_revision = 'cccf36f07905'
branch_labels = None
depends_on = None


def upgrade():
    # Add engagement_multiplier column to users table
    op.add_column('users', sa.Column('engagement_multiplier', sa.Float(), nullable=False, server_default='1.0'))
    
    # Create index for faster queries filtering featured accounts
    op.create_index('ix_users_engagement_multiplier', 'users', ['engagement_multiplier'])


def downgrade():
    # Drop index
    op.drop_index('ix_users_engagement_multiplier', table_name='users')
    
    # Drop column
    op.drop_column('users', 'engagement_multiplier')
