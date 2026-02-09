"""add badge_type to badges and source to user_badges

Revision ID: b1a2c3d4e5f6
Revises: fe051ac3666b
Create Date: 2025-02-05 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b1a2c3d4e5f6'
down_revision = 'fe051ac3666b'
branch_labels = None
depends_on = None


def upgrade():
    """Add badge_type to badges and source to user_badges.

    This migration needs to work on both Postgres (prod) and SQLite (dev).
    SQLite does not support the same ALTER COLUMN syntax as Postgres, so we
    only tighten NOT NULL + server_default constraints on non-SQLite
    backends. Dev SQLite keeps the columns nullable, but data is still
    backfilled the same way.
    """
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Add new columns (works on both SQLite and Postgres)
    op.add_column('badges', sa.Column('badge_type', sa.String(20), nullable=True))
    op.add_column('user_badges', sa.Column('source', sa.String(50), nullable=True))

    # Set default values for existing records
    op.execute("UPDATE badges SET badge_type = 'commercial' WHERE badge_type IS NULL")

    # Update university badges to have 'uni' type based on price (free badges with university pattern)
    op.execute("""
        UPDATE badges 
        SET badge_type = 'uni' 
        WHERE price_ksh = 0 
        AND (name LIKE '%Member' OR image_url LIKE '%uni-logos-badges%')
    """)

    # Update free badges that aren't university badges
    op.execute("""
        UPDATE badges 
        SET badge_type = 'free' 
        WHERE price_ksh = 0 
        AND badge_type = 'commercial'
    """)

    # Set source for existing user badges - assume 'purchase' for commercial, 'auto_award' for uni
    op.execute("UPDATE user_badges SET source = 'purchase' WHERE source IS NULL")
    op.execute("""
        UPDATE user_badges 
        SET source = 'auto_award' 
        WHERE badge_id IN (SELECT id FROM badges WHERE badge_type = 'uni')
    """)

    # On Postgres (and other backends that support it), make columns non-nullable
    # after setting defaults. SQLite's dialect does not support this ALTER
    # syntax; dev SQLite will keep them nullable, which is acceptable.
    if dialect != 'sqlite':
        op.alter_column('badges', 'badge_type', nullable=False, server_default='commercial')
        op.alter_column('user_badges', 'source', nullable=False, server_default='purchase')


def downgrade():
    op.drop_column('badges', 'badge_type')
    op.drop_column('user_badges', 'source')
