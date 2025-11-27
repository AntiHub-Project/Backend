"""add_beta_field_to_users

Revision ID: 0dcd8c4a8684
Revises: 479a6b2e689d
Create Date: 2025-11-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0dcd8c4a8684'
down_revision: Union[str, None] = '479a6b2e689d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add beta field to users table with default value 0
    op.add_column('users', sa.Column('beta', sa.Integer(), nullable=False, server_default='0', comment='是否加入beta计划'))


def downgrade() -> None:
    # Remove beta field from users table
    op.drop_column('users', 'beta')
