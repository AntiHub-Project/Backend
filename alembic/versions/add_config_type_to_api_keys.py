"""add_config_type_to_api_keys

Revision ID: add_config_type
Revises: 0dcd8c4a8684
Create Date: 2025-11-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_config_type'
down_revision: Union[str, None] = '0dcd8c4a8684'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 添加config_type字段到api_keys表
    op.add_column('api_keys', sa.Column('config_type', sa.String(length=50), nullable=False, server_default='antigravity', comment='配置类型：antigravity 或 kiro'))

def downgrade() -> None:
    # 删除config_type字段
    op.drop_column('api_keys', 'config_type')