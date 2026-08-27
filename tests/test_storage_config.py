"""Storage backend selection and optional PostgreSQL integration tests."""

import os

import pytest

from medagent_hospital.web.hospital_store import HospitalRecordStore, create_hospital_store


def test_storage_factory_defaults_to_sqlite(tmp_path) -> None:
    store = create_hospital_store(db_path=tmp_path / "records.db")
    assert isinstance(store, HospitalRecordStore)
    store.close()


@pytest.mark.integration
def test_postgres_store_roundtrip_when_database_url_is_configured() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL 未配置")
    pytest.importorskip("psycopg")
    from medagent_hospital.web.postgres_store import PostgresRecordStore

    store = PostgresRecordStore(database_url)
    store.upsert_agent("test-agent", "test", "测试 Agent")
    store.create_session("storage-test", {"id": "P-STORAGE"})
    store.add_message("storage-test", "test-agent", "agent", "roundtrip")
    assert store.get_session("storage-test")["patient"]["id"] == "P-STORAGE"
    assert store.list_messages("storage-test")[0]["content"] == "roundtrip"
    store.close()
