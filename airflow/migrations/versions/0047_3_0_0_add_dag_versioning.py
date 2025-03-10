#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""
add dag versioning.

Revision ID: 2b47dc6bc8df
Revises: d03e4a635aa3
Create Date: 2024-10-09 05:44:04.670984

"""

from __future__ import annotations

import sqlalchemy as sa
import sqlalchemy_jsonfield
from alembic import op
from sqlalchemy import LargeBinary, Table
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy_utils import UUIDType

from airflow.migrations.db_types import StringID
from airflow.models.base import ID_LEN, naming_convention
from airflow.settings import json
from airflow.utils import timezone
from airflow.utils.sqlalchemy import UtcDateTime

# revision identifiers, used by Alembic.
revision = "2b47dc6bc8df"
down_revision = "d03e4a635aa3"
branch_labels = None
depends_on = None
airflow_version = "3.0.0"


def _delete_serdag_and_code():
    op.execute(sa.text("DELETE FROM serialized_dag"))
    op.execute(sa.text("DELETE FROM dag_code"))


# The below tables helps us use the recreate_always feature of batch_alter_table and makes
# this migration work in offline mode.
old_dagcode_table = Table(
    "dag_code",
    sa.MetaData(naming_convention=naming_convention),
    sa.Column("fileloc_hash", sa.BigInteger(), nullable=False, primary_key=True),
    sa.Column("fileloc", sa.String(length=2000), nullable=False),
    sa.Column("last_updated", UtcDateTime(), nullable=False),
    sa.Column("source_code", sa.Text().with_variant(MEDIUMTEXT(), "mysql"), nullable=False),
)

old_serialized_table = Table(
    "serialized_dag",
    sa.MetaData(naming_convention=naming_convention),
    sa.Column("dag_id", sa.String(ID_LEN), nullable=False, primary_key=True),
    sa.Column("fileloc", sa.String(length=2000), nullable=False),
    sa.Column("fileloc_hash", sa.BigInteger(), nullable=False),
    sa.Column("data", sqlalchemy_jsonfield.JSONField(json=json), nullable=True),
    sa.Column("data_compressed", LargeBinary, nullable=True),
    sa.Column("dag_hash", sa.String(32), nullable=False),
    sa.Column("last_updated", UtcDateTime(), nullable=False),
    sa.Column("processor_subdir", sa.String(2000)),
    sa.Index("idx_fileloc_hash", "fileloc_hash", unique=False),
)


def upgrade():
    """Apply add dag versioning."""
    # Before creating the dag_version table, we need to delete the existing serialized_dag and dag_code tables
    _delete_serdag_and_code()
    op.create_table(
        "dag_version",
        sa.Column("id", UUIDType(binary=False), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("dag_id", StringID(), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False, default=timezone.utcnow),
        sa.Column(
            "last_updated", UtcDateTime(), nullable=False, default=timezone.utcnow, onupdate=timezone.utcnow
        ),
        sa.ForeignKeyConstraint(
            ("dag_id",), ["dag.dag_id"], name=op.f("dag_version_dag_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("dag_version_pkey")),
        sa.UniqueConstraint("dag_id", "version_number", name="dag_id_v_name_v_number_unique_constraint"),
    )
    with op.batch_alter_table(
        "dag_code", recreate="always", naming_convention=naming_convention, copy_from=old_dagcode_table
    ) as batch_op:
        batch_op.drop_constraint("dag_code_pkey", type_="primary")
        batch_op.add_column(
            sa.Column("id", UUIDType(binary=False), primary_key=True), insert_before="fileloc_hash"
        )
        batch_op.create_primary_key("dag_code_pkey", ["id"])
        batch_op.add_column(sa.Column("dag_version_id", UUIDType(binary=False), nullable=False))
        batch_op.create_foreign_key(
            batch_op.f("dag_code_dag_version_id_fkey"),
            "dag_version",
            ["dag_version_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_unique_constraint("dag_code_dag_version_id_uq", ["dag_version_id"])
        batch_op.add_column(sa.Column("source_code_hash", sa.String(length=32), nullable=False))
        batch_op.drop_column("fileloc_hash")
        batch_op.add_column(sa.Column("dag_id", sa.String(length=250), nullable=False))
        batch_op.add_column(sa.Column("created_at", UtcDateTime(), nullable=False, default=timezone.utcnow))
        batch_op.alter_column("last_updated", nullable=False, onupdate=timezone.utcnow)

    with op.batch_alter_table(
        "serialized_dag",
        recreate="always",
        naming_convention=naming_convention,
        copy_from=old_serialized_table,
    ) as batch_op:
        batch_op.drop_constraint("serialized_dag_pkey", type_="primary")
        batch_op.add_column(sa.Column("id", UUIDType(binary=False), primary_key=True))
        batch_op.drop_index("idx_fileloc_hash")
        batch_op.drop_column("fileloc_hash")
        batch_op.drop_column("fileloc")
        batch_op.create_primary_key("serialized_dag_pkey", ["id"])
        batch_op.add_column(sa.Column("dag_version_id", UUIDType(binary=False), nullable=False))
        batch_op.create_foreign_key(
            batch_op.f("serialized_dag_dag_version_id_fkey"),
            "dag_version",
            ["dag_version_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_unique_constraint("serialized_dag_dag_version_id_uq", ["dag_version_id"])
        batch_op.add_column(sa.Column("created_at", UtcDateTime(), nullable=False, default=timezone.utcnow))

    with op.batch_alter_table("task_instance", schema=None) as batch_op:
        batch_op.add_column(sa.Column("dag_version_id", UUIDType(binary=False)))
        batch_op.create_foreign_key(
            batch_op.f("task_instance_dag_version_id_fkey"),
            "dag_version",
            ["dag_version_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("task_instance_history", schema=None) as batch_op:
        batch_op.add_column(sa.Column("dag_version_id", UUIDType(binary=False)))

    with op.batch_alter_table("dag_run", schema=None) as batch_op:
        batch_op.drop_column("dag_hash")


def downgrade():
    """Unapply add dag versioning."""
    # Going down from here, the way we serialize DAG changes, so we need to delete the dag_version table
    # which in turn deletes the serialized dag and dag code tables.
    op.execute(sa.text("DELETE FROM dag_version"))
    with op.batch_alter_table("task_instance_history", schema=None) as batch_op:
        batch_op.drop_column("dag_version_id")

    with op.batch_alter_table("task_instance", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("task_instance_dag_version_id_fkey"), type_="foreignkey")
        batch_op.drop_column("dag_version_id")

    with op.batch_alter_table("dag_code", schema=None) as batch_op:
        batch_op.drop_column("id")
        batch_op.drop_constraint(batch_op.f("dag_code_dag_version_id_fkey"), type_="foreignkey")
        batch_op.drop_column("dag_version_id")
        batch_op.add_column(sa.Column("fileloc_hash", sa.BigInteger, nullable=False))
        batch_op.create_primary_key("dag_code_pkey", ["fileloc_hash"])
        batch_op.drop_column("source_code_hash")
        batch_op.drop_column("dag_id")
        batch_op.drop_column("created_at")

    with op.batch_alter_table("serialized_dag", schema=None, naming_convention=naming_convention) as batch_op:
        batch_op.drop_column("id")
        batch_op.add_column(sa.Column("fileloc", sa.String(length=2000), autoincrement=False, nullable=False))
        batch_op.add_column(sa.Column("fileloc_hash", sa.BIGINT(), autoincrement=False, nullable=False))
        batch_op.create_index("idx_fileloc_hash", ["fileloc_hash"], unique=False)
        batch_op.create_primary_key("serialized_dag_pkey", ["dag_id"])
        batch_op.drop_constraint(batch_op.f("serialized_dag_dag_version_id_fkey"), type_="foreignkey")
        batch_op.drop_column("dag_version_id")
        batch_op.drop_column("created_at")

    with op.batch_alter_table("dag_run", schema=None) as batch_op:
        batch_op.add_column(sa.Column("dag_hash", sa.String(length=32), autoincrement=False, nullable=True))

    op.drop_table("dag_version")
