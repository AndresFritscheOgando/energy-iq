"""Migrated catalog matches the spec and the ORM (spec 0009/0001 AC-2, AC-3).

``alembic check`` ignores CHECK constraints and expression indexes, so the
exact names are asserted here from ``pg_constraint`` and ``pg_indexes``, and
the app role's grants from the information schema.
"""

import pytest
from alembic import command
from sqlalchemy import Engine, text

from energyiq.platform.db import alembic_config, script_head
from energyiq.platform.schema import load_metadata

pytestmark = pytest.mark.db

APP_ROLE = "energyiq_app"
TABLES = {
    "users",
    "sessions",
    "auth_attempts",
    "properties",
    "meters",
    "meter_events",
    "readings",
    "audit_events",
    "idempotency_keys",
    "invoices",
    "invoice_revisions",
    "invoice_current_periods",
    "source_documents",
    "extraction_runs",
}

CONSTRAINTS = {
    "pk_users",
    "uq_users_email",
    "ck_users_email_length",
    "pk_sessions",
    "fk_sessions_user_id_users",
    "uq_sessions_token_hash",
    "ck_sessions_token_hash_length",
    "pk_auth_attempts",
    "ck_auth_attempts_kind",
    "pk_properties",
    "fk_properties_owner_user_id_users",
    "ck_properties_nickname_length",
    "ck_properties_region_length",
    "ck_properties_timezone_length",
    "pk_meters",
    "fk_meters_property_id_properties",
    "ck_meters_distributor",
    "ck_meters_label_length",
    "ck_meters_register_digits_range",
    "ck_meters_active_deactivated",
    "pk_meter_events",
    "fk_meter_events_meter_id_meters",
    "fk_meter_events_created_by_users",
    "fk_meter_events_decided_by_users",
    "ck_meter_events_event_type",
    "ck_meter_events_status",
    "ck_meter_events_note_length",
    "ck_meter_events_decision_pair",
    "pk_readings",
    "fk_readings_meter_id_meters",
    "fk_readings_created_by_users",
    "ck_readings_cumulative_kwh_nonnegative",
    "ck_readings_source",
    "ck_readings_status",
    "pk_audit_events",
    "fk_audit_events_actor_user_id_users",
    "pk_idempotency_keys",
    "fk_idempotency_keys_user_id_users",
    "ck_idempotency_keys_key_length",
    "ck_idempotency_keys_request_hash_length",
    "ck_idempotency_keys_response_pair",
    "pk_invoices",
    "fk_invoices_meter_id_meters",
    "fk_invoices_owner_id_users",
    "fk_invoices_current_revision",
    "pk_invoice_revisions",
    "fk_invoice_revisions_invoice",
    "fk_invoice_revisions_actor",
    "fk_invoice_revisions_previous",
    "uq_invoice_revisions_number",
    "ck_invoice_revisions_status",
    "ck_invoice_revisions_period_order",
    "ck_invoice_revisions_billed_kwh_nonnegative",
    "ck_invoice_revisions_total_nonnegative",
    "ck_invoice_revisions_energy_nonnegative",
    "fk_invoice_revisions_source_document",
    "pk_source_documents",
    "uq_source_documents_storage_key",
    "fk_source_documents_owner_id_users",
    "fk_source_documents_property_id_properties",
    "fk_source_documents_meter_id_meters",
    "ck_source_documents_sha256_length",
    "ck_source_documents_mime_type",
    "ck_source_documents_size_positive",
    "ck_source_documents_purge_after_delete",
    "pk_extraction_runs",
    "fk_runs_document",
    "uq_extraction_runs_number",
    "ck_extraction_runs_state",
    "ck_extraction_runs_attempts_nonnegative",
    "ck_extraction_runs_running_has_lease",
    "ck_extraction_runs_failed_has_code",
    "pk_invoice_current_periods",
    "fk_invoice_periods_invoice",
    "fk_invoice_periods_meter",
    "fk_invoice_periods_revision",
}

INDEXES = {
    "pk_users",
    "uq_users_email",
    "pk_sessions",
    "ix_sessions_user_id",
    "uq_sessions_token_hash",
    "pk_auth_attempts",
    "ix_auth_attempts_email_key",
    "ix_auth_attempts_client_key",
    "pk_properties",
    "ix_properties_owner_user_id",
    "uq_properties_owner_nickname_active",
    "pk_meters",
    "ix_meters_property_id",
    "uq_meters_property_label_active",
    "pk_meter_events",
    "ix_meter_events_created_by",
    "ix_meter_events_decided_by",
    "ix_meter_events_meter_effective",
    "pk_readings",
    "ix_readings_created_by",
    "ix_readings_meter_recorded",
    "uq_readings_meter_instant_active",
    "pk_audit_events",
    "ix_audit_events_actor_user_id",
    "ix_audit_events_entity",
    "pk_idempotency_keys",
    "ix_idempotency_keys_expires_at",
    "pk_invoices",
    "ix_invoices_meter_id",
    "ix_invoices_owner_id",
    "ix_invoices_current_revision_id",
    "pk_invoice_revisions",
    "ix_invoice_revisions_invoice_id",
    "ix_invoice_revisions_actor_id",
    "ix_invoice_revisions_previous_revision_id",
    "ix_invoice_revisions_source_document_id",
    "pk_source_documents",
    "uq_source_documents_storage_key",
    "ix_source_documents_owner_id",
    "ix_source_documents_property_id",
    "ix_source_documents_meter_id",
    "pk_extraction_runs",
    "uq_extraction_runs_number",
    "ix_extraction_runs_document_id",
    "uq_extraction_runs_active_document",
    "ix_extraction_runs_claim",
    "uq_invoice_revisions_number",
    "pk_invoice_current_periods",
    "ix_invoice_current_periods_meter_id",
    "ix_invoice_current_periods_current_revision_id",
    "ex_invoice_current_periods_meter_overlap",
}

PARTIAL_UNIQUE_INDEXES = {
    "uq_properties_owner_nickname_active": (
        "(owner_user_id, lower(nickname)) WHERE (archived_at IS NULL)"
    ),
    "uq_meters_property_label_active": "(property_id, lower(label)) WHERE active",
    "uq_readings_meter_instant_active": (
        "(meter_id, recorded_at) WHERE (status <> 'voided'::text)"
    ),
}

COLUMN_UPDATES = {
    ("source_documents", "deleted_at"),
    ("source_documents", "purged_at"),
    *(
        ("extraction_runs", name)
        for name in (
            "state",
            "attempts",
            "lease_owner",
            "lease_expires_at",
            "error_code",
            "started_at",
            "finished_at",
            "model",
            "prompt_version",
            "output",
        )
    ),
    ("invoices", "current_revision_id"),
    ("invoice_revisions", "status"),
    ("invoice_revisions", "confirmed_at"),
    ("invoice_current_periods", "current_revision_id"),
    ("invoice_current_periods", "local_daterange"),
    ("users", "password_hash"),
    ("users", "disabled_at"),
    ("sessions", "last_seen_at"),
    ("sessions", "revoked_at"),
    ("properties", "nickname"),
    ("properties", "region"),
    ("properties", "timezone"),
    ("properties", "updated_at"),
    ("properties", "archived_at"),
    ("meters", "label"),
    ("meters", "register_digits"),
    ("meters", "active"),
    ("meters", "deactivated_at"),
    ("meters", "updated_at"),
    ("readings", "status"),
    ("readings", "status_changed_at"),
    ("meter_events", "status"),
    ("meter_events", "decided_by"),
    ("meter_events", "decided_at"),
    *(
        ("idempotency_keys", name)
        for name in (
            "user_id",
            "key",
            "operation",
            "request_hash",
            "response_status",
            "response_body",
            "created_at",
            "expires_at",
        )
    ),
}


def _names(engine: Engine, sql: str) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(text(sql), {"tables": list(TABLES)}).scalars().all()
        )


def test_database_is_at_the_script_head(migrator_engine: Engine) -> None:
    with migrator_engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()

    assert revision == script_head()


def test_exactly_the_core_tables_exist(migrator_engine: Engine) -> None:
    with migrator_engine.connect() as connection:
        names = set(
            connection.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                    " AND tablename <> 'alembic_version'"
                )
            ).scalars()
        )

    assert names == TABLES


def test_orm_metadata_matches_the_migration(migrator_engine: Engine) -> None:
    """``alembic check`` raises if autogenerate would emit any operation."""
    config = alembic_config()
    with migrator_engine.connect() as connection:
        config.attributes["connection"] = connection
        command.check(config)

    assert set(load_metadata().tables) == TABLES


def test_exact_constraint_names(migrator_engine: Engine) -> None:
    names = _names(
        migrator_engine,
        "SELECT c.conname FROM pg_constraint c"
        " JOIN pg_class t ON t.oid = c.conrelid"
        " JOIN pg_namespace n ON n.oid = t.relnamespace"
        " WHERE n.nspname = 'public' AND t.relname = ANY(:tables)"
        " AND c.contype IN ('p', 'f', 'u', 'c')",
    )

    assert names == CONSTRAINTS


def test_exact_index_names(migrator_engine: Engine) -> None:
    names = _names(
        migrator_engine,
        "SELECT indexname FROM pg_indexes"
        " WHERE schemaname = 'public' AND tablename = ANY(:tables)",
    )

    assert names == INDEXES


def test_partial_unique_index_definitions(migrator_engine: Engine) -> None:
    with migrator_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes"
                " WHERE schemaname = 'public' AND indexname = ANY(:names)"
            ),
            {"names": list(PARTIAL_UNIQUE_INDEXES)},
        ).all()

    definitions = {name: definition for name, definition in rows}
    assert set(definitions) == set(PARTIAL_UNIQUE_INDEXES)
    for name, tail in PARTIAL_UNIQUE_INDEXES.items():
        assert definitions[name].startswith("CREATE UNIQUE INDEX")
        assert definitions[name].endswith(tail), definitions[name]


def test_every_foreign_key_restricts_deletes_and_is_indexed(
    migrator_engine: Engine,
) -> None:
    with migrator_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT c.conname, c.confdeltype, a.attname, t.relname,"
                " EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.conrelid"
                "  AND i.indkey[0] = c.conkey[1]) AS indexed"
                " FROM pg_constraint c"
                " JOIN pg_class t ON t.oid = c.conrelid"
                " JOIN pg_attribute a ON a.attrelid = c.conrelid"
                "  AND a.attnum = c.conkey[1]"
                " WHERE c.contype = 'f' AND t.relname = ANY(:tables)"
            ),
            {"tables": list(TABLES)},
        ).all()

    assert len(rows) == 24
    for name, delete_rule, column, table, indexed in rows:
        assert delete_rule == "r", f"{name} is not ON DELETE RESTRICT"
        assert indexed, f"{table}.{column} ({name}) has no leading index"


def test_kwh_column_is_numeric_18_6(migrator_engine: Engine) -> None:
    with migrator_engine.connect() as connection:
        precision, scale = connection.execute(
            text(
                "SELECT numeric_precision, numeric_scale"
                " FROM information_schema.columns"
                " WHERE table_name = 'readings' AND column_name = 'cumulative_kwh'"
            )
        ).one()

    assert (precision, scale) == (18, 6)


def test_every_instant_is_timestamptz(migrator_engine: Engine) -> None:
    with migrator_engine.connect() as connection:
        types = set(
            connection.execute(
                text(
                    "SELECT data_type FROM information_schema.columns"
                    " WHERE table_name = ANY(:tables)"
                    " AND (column_name LIKE '%\\_at' ESCAPE '\\')"
                ),
                {"tables": list(TABLES)},
            ).scalars()
        )

    assert types == {"timestamp with time zone"}


def test_app_role_table_grants(migrator_engine: Engine) -> None:
    with migrator_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT table_name, privilege_type"
                " FROM information_schema.table_privileges"
                " WHERE grantee = :role AND table_schema = 'public'"
            ),
            {"role": APP_ROLE},
        ).all()

    expected = {(table, p) for table in TABLES for p in ("SELECT", "INSERT")}
    expected.add(("alembic_version", "SELECT"))
    expected.add(("idempotency_keys", "UPDATE"))
    assert set(map(tuple, rows)) == expected


def test_app_role_column_update_grants(migrator_engine: Engine) -> None:
    with migrator_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT table_name, column_name"
                " FROM information_schema.column_privileges"
                " WHERE grantee = :role AND privilege_type = 'UPDATE'"
                " AND table_schema = 'public'"
            ),
            {"role": APP_ROLE},
        ).all()

    assert set(map(tuple, rows)) == COLUMN_UPDATES


@pytest.mark.parametrize("sequence", ["audit_events_id_seq", "auth_attempts_id_seq"])
def test_app_role_may_use_the_identity_sequences(
    migrator_engine: Engine, sequence: str
) -> None:
    with migrator_engine.connect() as connection:
        allowed = connection.execute(
            text("SELECT has_sequence_privilege(:role, :sequence, 'USAGE')"),
            {"role": APP_ROLE, "sequence": f"public.{sequence}"},
        ).scalar_one()

    assert allowed is True


def test_app_role_owns_nothing_and_cannot_create(migrator_engine: Engine) -> None:
    with migrator_engine.connect() as connection:
        owned = connection.execute(
            text(
                "SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner"
                " WHERE r.rolname = :role"
            ),
            {"role": APP_ROLE},
        ).scalar_one()
        can_create = connection.execute(
            text("SELECT has_schema_privilege(:role, 'public', 'CREATE')"),
            {"role": APP_ROLE},
        ).scalar_one()

    assert owned == 0
    assert can_create is False
