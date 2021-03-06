"""PVC version 0.7

Revision ID: 88c8514684f7
Revises: 2d1daa722a0a
Create Date: 2020-02-16 19:49:50.126265

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '88c8514684f7'
down_revision = '2d1daa722a0a'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('ova',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('ovf', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('ova_volume',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ova', sa.Integer(), nullable=False),
    sa.Column('pool', sa.Text(), nullable=False),
    sa.Column('volume_name', sa.Text(), nullable=False),
    sa.Column('volume_format', sa.Text(), nullable=False),
    sa.Column('disk_id', sa.Text(), nullable=False),
    sa.Column('disk_size_gb', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['ova'], ['ova.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.alter_column('network', 'network_template',
               existing_type=sa.INTEGER(),
               nullable=False)
    op.add_column('network_template', sa.Column('ova', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'network_template', 'ova', ['ova'], ['id'])
    op.add_column('profile', sa.Column('ova', sa.Integer(), nullable=True))
    op.add_column('profile', sa.Column('profile_type', sa.Text(), nullable=False))
    op.create_foreign_key(None, 'profile', 'ova', ['ova'], ['id'])
    op.alter_column('storage', 'storage_template',
               existing_type=sa.INTEGER(),
               nullable=False)
    op.add_column('storage_template', sa.Column('ova', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'storage_template', 'ova', ['ova'], ['id'])
    op.add_column('system_template', sa.Column('ova', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'system_template', 'ova', ['ova'], ['id'])
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'system_template', type_='foreignkey')
    op.drop_column('system_template', 'ova')
    op.drop_constraint(None, 'storage_template', type_='foreignkey')
    op.drop_column('storage_template', 'ova')
    op.alter_column('storage', 'storage_template',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.drop_constraint(None, 'profile', type_='foreignkey')
    op.drop_column('profile', 'profile_type')
    op.drop_column('profile', 'ova')
    op.drop_constraint(None, 'network_template', type_='foreignkey')
    op.drop_column('network_template', 'ova')
    op.alter_column('network', 'network_template',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.drop_table('ova_volume')
    op.drop_table('ova')
    # ### end Alembic commands ###
