"""Integration tests against real MySQL.

Requires: pip install eliza-dq[mysql]
Service:  mysql:8 on localhost:3306, db=eliza_test, user=root, pw=root
"""

import os

import pytest

from eliza.sql_runner import check_sql

from .conftest import INLINE_CHECKS, TOTAL_ROWS, find_check, make_check_config

pytestmark = pytest.mark.mysql

MYSQL_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASS = os.environ.get("MYSQL_PASSWORD", "root")
MYSQL_DB = os.environ.get("MYSQL_DATABASE", "eliza_test")

DIALECT = "mysql"
TABLE = "eliza_test"
REF_TABLE = "eliza_ref_statuses"

SETUP_SQL = [
    f"DROP TABLE IF EXISTS {TABLE}",
    f"DROP TABLE IF EXISTS {REF_TABLE}",
    f"""CREATE TABLE {TABLE} (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(100),
        email VARCHAR(200),
        amount DECIMAL(10,2),
        status VARCHAR(20),
        code VARCHAR(10),
        score INT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    f"""CREATE TABLE {REF_TABLE} (
        status_name VARCHAR(20) PRIMARY KEY
    )""",
    f"INSERT INTO {REF_TABLE} (status_name) VALUES ('active'), ('pending')",
    f"""INSERT INTO {TABLE} (name, email, amount, status, code, score) VALUES
        ('Alice', 'alice@test.com', 100.50, 'active', 'ABC12', 80),
        ('Bob',   'bob@test.com',   50.00,  'active', 'DEF34', 90),
        (NULL,    'invalid-email',  -10.00, 'closed', 'AB1',   30),
        (NULL,    'dave@test.com',  200.00, 'active', 'CDEF5', 110),
        ('Eve',   '',               0.50,   'pending','EF2',   50),
        (NULL,    'frank@test.com', -5.25,  'active', 'GHI78', 70),
        ('',      'grace@test.com', 75.00,  'active', 'JK3',   85),
        ('Heidi', 'heidi@test.com', 300.00, 'active', 'LMN90', 95),
        ('Ivan',  'bad-email',      25.00,  'closed', 'OP4',   40),
        ('Jane',  'jane@test.com',  150.00, 'active', 'QRS12', 65)""",
]


@pytest.fixture(scope="module")
def db():
    import threading

    pymysql = pytest.importorskip("pymysql")
    connect_args = dict(host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASS, database=MYSQL_DB)
    try:
        conn = pymysql.connect(**connect_args)
    except pymysql.OperationalError:
        pytest.skip("MySQL not available")
    cur = conn.cursor()
    for sql in SETUP_SQL:
        cur.execute(sql)
    conn.commit()
    conn.close()

    _local = threading.local()

    def executor(sql):
        if not hasattr(_local, "conn"):
            _local.conn = pymysql.connect(**connect_args)
        cur2 = _local.conn.cursor()
        cur2.execute(sql)
        columns = [desc[0] for desc in cur2.description]
        return [dict(zip(columns, row)) for row in cur2.fetchall()]

    yield executor


@pytest.mark.parametrize(
    "check_name,column,params,expected",
    INLINE_CHECKS,
    ids=[c[0] for c in INLINE_CHECKS],
)
def test_inline_check(db, check_name, column, params, expected):
    cfg = make_check_config(check_name, column, params)
    result = check_sql(db, checks_list=[cfg], table=TABLE, dialect=DIALECT, samples=False)
    assert result.checks[0].fail_count == expected
    assert result.checks[0].status == ("pass" if expected == 0 else "fail")


def test_unique(db):
    cfg = {"column": "status", "check": "unique"}
    result = check_sql(db, checks_list=[cfg], table=TABLE, dialect=DIALECT, samples=False)
    c = find_check(result, "unique", "status")
    assert c.fail_count == 2


def test_freshness_pass(db):
    cfg = {"column": "updated_at", "check": "freshness", "max_age": "48h"}
    result = check_sql(db, checks_list=[cfg], table=TABLE, dialect=DIALECT, samples=False)
    c = find_check(result, "freshness", "updated_at")
    assert c.status == "pass"


def test_row_count(db):
    cfg = {"check": "row_count", "min": 5, "max": 20}
    result = check_sql(db, checks_list=[cfg], table=TABLE, dialect=DIALECT, samples=False)
    c = find_check(result, "row_count")
    assert c.status == "pass"
    assert result.total_rows == TOTAL_ROWS


def test_reference(db):
    cfg = {
        "column": "status",
        "check": "reference",
        "reference_table": REF_TABLE,
        "reference_column": "status_name",
    }
    result = check_sql(db, checks_list=[cfg], table=TABLE, dialect=DIALECT, samples=False)
    c = find_check(result, "reference", "status")
    assert c.fail_count == 2


def test_cross_column(db):
    cfg = {"check": "cross_column", "column_a": "score", "column_b": "amount"}
    result = check_sql(db, checks_list=[cfg], table=TABLE, dialect=DIALECT, samples=False)
    c = result.checks[0]
    assert c.fail_count == 6


def test_all_checks_combined(db):
    checks_list = [make_check_config(n, c, p) for n, c, p, _ in INLINE_CHECKS]
    checks_list.append({"column": "status", "check": "unique"})
    checks_list.append({"column": "updated_at", "check": "freshness", "max_age": "48h"})
    checks_list.append({"check": "row_count", "min": 5, "max": 20})
    result = check_sql(db, checks_list=checks_list, table=TABLE, dialect=DIALECT, samples=False)
    failed = [c for c in result.checks if c.status == "fail"]
    passed = [c for c in result.checks if c.status == "pass"]
    assert len(failed) == 11
    assert len(passed) == 2


def test_samples_collected(db):
    cfg = make_check_config("not_null", "name", {})
    result = check_sql(db, checks_list=[cfg], table=TABLE, dialect=DIALECT, samples=True, samples_limit=5)
    assert "name:not_null" in result.samples
    rows = result.samples["name:not_null"]
    assert len(rows) <= 5
    assert all(r.get("name") is None for r in rows)
