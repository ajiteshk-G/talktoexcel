# Copyright 2026 Google LLC

import pytest
from app.ingestion import sanitize_headers, generate_workbook_id, generate_table_name, sanitize_user_id
from app.tools import validate_sql


def test_sanitize_headers():
    raw_headers = [
        "Product Name",
        "Category",
        "Units Sold",
        "Revenue USD (%)",
        "Sale Date",
        None,
        "",
        "Sale Date",
        "123_numeric",
    ]
    cleaned = sanitize_headers(raw_headers)
    assert cleaned[0] == "product_name"
    assert cleaned[1] == "category"
    assert cleaned[2] == "units_sold"
    assert cleaned[3] == "revenue_usd"
    assert cleaned[4] == "sale_date"
    assert cleaned[5] == "col_6"
    assert cleaned[6] == "col_7"
    assert cleaned[7] == "sale_date_1"
    assert cleaned[8] == "col_123_numeric"


def test_sanitize_user_id():
    assert sanitize_user_id("ajiteshk@google.com") == "ajiteshk"
    assert sanitize_user_id("finance-user.123@corp.com") == "finance_user_123"
    assert sanitize_user_id("") == "ajiteshk"
    assert sanitize_user_id(None) == "ajiteshk"


def test_workbook_and_table_name_generation():
    wb_id = generate_workbook_id("Quarterly Financials 2026.xlsx", user_id="ajiteshk@google.com")
    assert wb_id.startswith("wb_ajiteshk_quarterly_fi")
    tbl_name = generate_table_name(wb_id, "Balance Sheet")
    assert tbl_name.startswith("wb_ajiteshk_")
    assert "balance_sheet" in tbl_name


def test_sql_validator_allows_user_tables():
    user = "ajiteshk"
    valid_queries = [
        f"SELECT * FROM `mb-poc-352009.adhoc_excel_analytics.wb_{user}_test`",
        f"SELECT department, SUM(spend) FROM `wb_{user}_sales` GROUP BY department ORDER BY 2 DESC",
        f"WITH summary AS (SELECT department, spend FROM `wb_{user}_data`) SELECT * FROM summary",
    ]
    for q in valid_queries:
        is_valid, err = validate_sql(q, user_slug=user)
        assert is_valid, f"Expected query to be valid: {q}, got error: {err}"


def test_sql_validator_blocks_cross_user_tables():
    user = "ajiteshk"
    other_user_queries = [
        "SELECT * FROM `mb-poc-352009.adhoc_excel_analytics.wb_john_test`",
        "SELECT * FROM wb_alice_financials",
        f"SELECT a.col FROM wb_{user}_test a JOIN wb_bob_secret b ON a.id = b.id",
    ]
    for q in other_user_queries:
        is_valid, err = validate_sql(q, user_slug=user)
        assert not is_valid, f"Expected query to be blocked for cross-user access: {q}"
        assert "Access Denied" in err or "does not belong to user" in err


def test_sql_validator_blocks_dangerous_operations():
    user = "ajiteshk"
    forbidden_queries = [
        f"DROP TABLE `mb-poc-352009.adhoc_excel_analytics.wb_{user}_test`",
        f"DELETE FROM `wb_{user}_test` WHERE 1=1",
        f"UPDATE `wb_{user}_test` SET val = 1",
        f"INSERT INTO `wb_{user}_test` VALUES (1, 2)",
        f"ALTER TABLE `wb_{user}_test` DROP COLUMN col1",
        f"TRUNCATE TABLE `wb_{user}_test`",
    ]
    for q in forbidden_queries:
        is_valid, err = validate_sql(q, user_slug=user)
        assert not is_valid, f"Expected query to be rejected: {q}"
