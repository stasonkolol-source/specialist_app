"""Миграции Alembic (DEVELOPMENT_PLAN 0.9): раунд-трип, одна head, объекты поиска."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.plugins.containers import PostgresInfo, run_alembic

pytestmark = pytest.mark.integration


def _ok(info: PostgresInfo, *args: str) -> str:
    result = run_alembic(info, *args)
    assert result.returncode == 0, f"alembic {' '.join(args)}:\n{result.stdout}\n{result.stderr}"
    return result.stdout + result.stderr


def test_roundtrip_single_head_and_no_drift(fresh_postgres: PostgresInfo) -> None:
    _ok(fresh_postgres, "upgrade", "head")
    _ok(fresh_postgres, "downgrade", "base")
    _ok(fresh_postgres, "upgrade", "head")
    check = _ok(fresh_postgres, "check")
    assert "No new upgrade operations detected" in check
    heads = [line for line in _ok(fresh_postgres, "heads").splitlines() if "(head)" in line]
    assert len(heads) == 1, heads


async def _scalar(conn: AsyncConnection, sql: str, **params: object) -> object:
    return (await conn.execute(text(sql), params)).scalar_one()


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Građevina", "gradjevina"),
        ("Електричар", "elektricar"),
        ("Čišćenje STANA", "ciscenje stana"),
        ("Đorđe", "djordje"),
    ],
)
async def test_search_norm_equivalences(
    db_connection: AsyncConnection, left: str, right: str
) -> None:
    same = await _scalar(
        db_connection, "SELECT platform.search_norm(:a) = platform.search_norm(:b)", a=left, b=right
    )
    assert same is True


async def test_russian_and_serbian_queries_match_documents(db_connection: AsyncConnection) -> None:
    doc = "setweight(platform.tsv_ru(:ru), 'A') || setweight(platform.tsv_sr(:sr), 'A')"
    for query in ("электрик", "električar", "elektricar", "електричар"):
        matched = await _scalar(
            db_connection,
            f"SELECT ({doc}) @@ platform.q_ru_sr(:q)",
            ru="Электрик",
            sr="Električar",
            q=query,
        )
        assert matched is True, query
    prefix = await _scalar(
        db_connection,
        "SELECT platform.tsv_sr(:d) @@ platform.q_prefix_ru_sr(:q)",
        d="Popravka veš mašina",
        q="popravka veš maš",
    )
    assert prefix is True


async def test_collations_sort_serbian_alphabet(db_connection: AsyncConnection) -> None:
    ordered = await _scalar(
        db_connection,
        "SELECT string_agg(w, ' ' ORDER BY w COLLATE platform.sr_latn_icu) "
        "FROM unnest(ARRAY['džem', 'dan', 'đak', 'čaj', 'ćup', 'cvet']) AS w",
    )
    assert ordered == "cvet čaj ćup dan džem đak"


async def test_procrastinate_schema_is_visible_to_app_role(db_connection: AsyncConnection) -> None:
    assert await _scalar(db_connection, "SELECT count(*) FROM procrastinate_jobs") == 0
    assert await _scalar(db_connection, "SHOW search_path") == "public, procrastinate"
