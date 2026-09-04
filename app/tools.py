# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Analytical and ingestion tools for BigQuery Conversational Analytics Agent.

Multi-Tenant User Isolation:
- Automatically extracts the logged-in user identity from ToolContext (user_id).
- Restricts GCS dropzone storage and browsing to gs://{bucket}/{user_id}/.
- Restricts BigQuery table creation, schema inspection, and querying to the user's tables (wb_{user_id}_*).
- Prevents cross-user table access or unauthorized data visibility.
"""

import base64
import datetime
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from google.adk.tools import ToolContext
from google.cloud import bigquery
import sqlparse

from app.ingestion import (
    DATASET_ID,
    DEFAULT_TTL_HOURS,
    DROPZONE_BUCKET,
    PROJECT_ID,
    ingest_file,
    list_dropzone_files as list_dropzone_impl,
    sanitize_user_id,
    upload_bytes_to_dropzone,
)

logger = logging.getLogger(__name__)

DISALLOWED_SQL_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "MERGE",
    "CALL",
    "CREATE",
    "GRANT",
    "REVOKE",
    "EXECUTE",
}


def resolve_user_id(tool_context: Optional[ToolContext] = None) -> str:
    """Extracts and sanitizes the active user identifier from ToolContext."""
    if tool_context is not None:
        if hasattr(tool_context, "user_id") and tool_context.user_id:
            return sanitize_user_id(tool_context.user_id)
        if hasattr(tool_context, "state") and tool_context.state:
            state_user = tool_context.state.get("user_id")
            if state_user:
                return sanitize_user_id(state_user)
    return sanitize_user_id(None)


def validate_sql(query: str, user_slug: str) -> Tuple[bool, Optional[str]]:
    """Validates that a SQL query is strictly read-only and ONLY accesses tables belonging to user_slug."""
    stripped = query.strip()
    if not stripped:
        return False, "Query is empty."

    parsed = sqlparse.parse(stripped)
    if not parsed:
        return False, "Failed to parse SQL query syntax."

    if len(parsed) > 1:
        return False, "Multiple SQL statements in a single execution are prohibited."

    statement = parsed[0]
    first_token = statement.token_first(skip_ws=True, skip_cm=True)
    if not first_token or first_token.value.upper() not in ("SELECT", "WITH"):
        token_name = first_token.value if first_token else "unknown"
        return False, f"Only SELECT or WITH queries are permitted. Got: {token_name}"

    for token in statement.flatten():
        val = token.value.upper()
        if val in DISALLOWED_SQL_KEYWORDS:
            return False, f"Prohibited SQL operation detected: '{val}'"

    # Multi-tenant security check: Ensure query only targets tables belonging to this user
    # Table naming standard: `wb_{user_slug}_...`
    # Check any tokens matching `wb_...`
    wb_tables = re.findall(r"wb_[a-zA-Z0-9_]+", stripped)
    for tbl in wb_tables:
        expected_prefix = f"wb_{user_slug}_"
        if not tbl.startswith(expected_prefix):
            return False, f"Access Denied: Table '{tbl}' does not belong to user '{user_slug}'. Cross-tenant access is blocked."

    return True, None


def upload_and_ingest_spreadsheet(
    filename: str,
    file_base64: str,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Uploads a spreadsheet file (.xlsx, .xls, .xlsm, .csv) directly from the conversation

    into the user's isolated Cloud Storage directory (gs://mb-poc-352009-excel-dropzone/{user_id}/{filename})
    and immediately flattens all sheets into BigQuery ephemeral tables with a 2-hour TTL.

    Args:
        filename: Name of the spreadsheet file (e.g. quarterly_revenue.xlsx).
        file_base64: Base64-encoded string of the spreadsheet binary content.

    Returns:
        A dict containing status, workbook_id, GCS URI, generated BigQuery tables, and column overviews.
    """
    user_slug = resolve_user_id(tool_context)
    try:
        file_bytes = base64.b64decode(file_base64)
        gcs_uri = upload_bytes_to_dropzone(
            file_bytes=file_bytes,
            filename=filename,
            user_id=user_slug,
        )
        return ingest_file(file_path_or_uri=gcs_uri, user_id=user_slug, original_filename=filename)
    except Exception as e:
        logger.exception(f"Upload and ingest failed for {filename}: {e}")
        return {"status": "FAILED", "error": str(e), "filename": filename, "user_id": user_slug}


def list_dropzone_files(tool_context: Optional[ToolContext] = None) -> Dict[str, Any]:
    """Lists spreadsheet files available in the current user's isolated dropzone directory

    (gs://mb-poc-352009-excel-dropzone/{user_id}/). Users only see files uploaded in their own directory.

    Returns:
        A dict containing status, dropzone bucket name, user directory, file count, and list of files.
    """
    user_slug = resolve_user_id(tool_context)
    files = list_dropzone_impl(user_id=user_slug, bucket_name=DROPZONE_BUCKET)
    return {
        "status": "SUCCESS",
        "dropzone_bucket": f"gs://{DROPZONE_BUCKET}",
        "user_directory": f"gs://{DROPZONE_BUCKET}/{user_slug}/",
        "user_id": user_slug,
        "file_count": len(files),
        "files": files,
    }


def ingest_spreadsheet(
    filename_or_gcs_uri: str,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Ingests an Excel (.xlsx, .xls, .xlsm) or CSV spreadsheet file from the user's isolated

    Cloud Storage directory into BigQuery ephemeral tables with a 2-hour TTL.

    Args:
        filename_or_gcs_uri: The filename (e.g. q1_financials.xlsx) or full GCS URI (gs://mb-poc-352009-excel-dropzone/{user_id}/q1_financials.xlsx).

    Returns:
        A dict containing the workbook ID, generated BigQuery tables for each sheet, row counts, and column names.
    """
    user_slug = resolve_user_id(tool_context)
    return ingest_file(file_path_or_uri=filename_or_gcs_uri, user_id=user_slug)


def list_available_spreadsheets(tool_context: Optional[ToolContext] = None) -> Dict[str, Any]:
    """Lists all active ingested spreadsheets, sheets, and BigQuery tables available for querying

    strictly belonging to the current user.

    Returns:
        A dict containing active workbooks, sheets, BigQuery table IDs, row counts, and expiration timestamps.
    """
    user_slug = resolve_user_id(tool_context)
    try:
        client = bigquery.Client(project=PROJECT_ID)
        registry_table_id = f"{PROJECT_ID}.{DATASET_ID}.excel_files_registry"
        query = f"""
            SELECT workbook_id, original_filename, sheet_name, table_name, full_table_id, row_count, column_count, ingested_at, expires_at
            FROM `{registry_table_id}`
            WHERE user_id = @user_id AND expires_at > CURRENT_TIMESTAMP()
            ORDER BY ingested_at DESC
            LIMIT 50
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("user_id", "STRING", user_slug),
            ]
        )
        job = client.query(query, job_config=job_config)
        results = job.result()
        items = []
        for r in results:
            items.append({
                "workbook_id": r["workbook_id"],
                "filename": r["original_filename"],
                "sheet_name": r["sheet_name"],
                "table_name": r["table_name"],
                "full_table_id": r["full_table_id"],
                "row_count": r["row_count"],
                "column_count": r["column_count"],
                "ingested_at": r["ingested_at"].isoformat() if r["ingested_at"] else None,
                "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
            })
        return {"status": "SUCCESS", "user_id": user_slug, "active_spreadsheets": items, "count": len(items)}
    except Exception as e:
        logger.warning(f"Registry query failed, falling back to prefix filtering: {e}")
        try:
            client = bigquery.Client(project=PROJECT_ID)
            dataset_ref = client.dataset(DATASET_ID)
            tables = list(client.list_tables(dataset_ref))
            user_prefix = f"wb_{user_slug}_"
            active = []
            for t in tables:
                if t.table_id.startswith(user_prefix) and not t.table_id.endswith("__metadata"):
                    active.append({
                        "table_name": t.table_id,
                        "full_table_id": f"{PROJECT_ID}.{DATASET_ID}.{t.table_id}",
                    })
            return {"status": "SUCCESS", "user_id": user_slug, "active_tables": active, "count": len(active)}
        except Exception as inner_e:
            return {"status": "ERROR", "error": str(inner_e)}


def get_sheet_details(
    table_name_or_sheet: str,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Retrieves schema information (column names and data types), total row count,

    and preview sample rows for a specific spreadsheet table.
    Enforces user isolation: only tables belonging to the current user can be inspected.

    Args:
        table_name_or_sheet: The table name to inspect (e.g. wb_user_q1_financials_..._q1_financials).

    Returns:
        A dict containing table_id, total rows, expiration time, column schema, and 3 preview rows.
    """
    user_slug = resolve_user_id(tool_context)
    raw_tbl = table_name_or_sheet.split(".")[-1]

    # Enforce user table ownership
    if not raw_tbl.startswith(f"wb_{user_slug}_"):
        return {
            "status": "PERMISSION_DENIED",
            "error": f"Access Denied: Table '{raw_tbl}' does not belong to user '{user_slug}'. Cross-tenant access is prohibited.",
        }

    try:
        client = bigquery.Client(project=PROJECT_ID)
        full_table_id = f"{PROJECT_ID}.{DATASET_ID}.{raw_tbl}"
        table = client.get_table(full_table_id)
        schema_info = [{"column": f.name, "type": f.field_type, "mode": f.mode} for f in table.schema]

        preview_query = f"SELECT * FROM `{full_table_id}` LIMIT 3"
        preview_res = client.query(preview_query).result()
        samples = []
        for r in preview_res:
            row_dict = {}
            for k, v in r.items():
                if isinstance(v, (datetime.date, datetime.datetime, datetime.time)):
                    row_dict[k] = v.isoformat()
                else:
                    row_dict[k] = v
            samples.append(row_dict)

        return {
            "status": "SUCCESS",
            "user_id": user_slug,
            "table_id": full_table_id,
            "table_name": table.table_id,
            "total_rows": table.num_rows,
            "expires_at": table.expires.isoformat() if table.expires else None,
            "columns": schema_info,
            "preview_samples": samples,
        }
    except Exception as e:
        logger.error(f"Error inspecting table {table_name_or_sheet}: {e}")
        return {"status": "ERROR", "error": str(e)}


def run_analytical_query(
    query: str,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Executes a safe, read-only GoogleSQL query against the BigQuery ad-hoc spreadsheet tables

    belonging to the current user, returning result rows and execution summary.
    Only SELECT and WITH statements are allowed. Queries attempting to access other users' tables are blocked.

    Args:
        query: The read-only GoogleSQL query to execute (e.g. SELECT department_name, SUM(actual_spend_usd) FROM `mb-poc-352009.adhoc_excel_analytics.wb_user_..._q1_financials` GROUP BY 1).

    Returns:
        A dict containing status, row_count, columns, and data rows.
    """
    user_slug = resolve_user_id(tool_context)
    is_valid, err = validate_sql(query, user_slug=user_slug)
    if not is_valid:
        return {"status": "PERMISSION_DENIED", "error": f"Security validation error: {err}"}

    upper_query = query.upper()
    if "LIMIT" not in upper_query:
        query = f"{query.strip().rstrip(';')} LIMIT 200"

    try:
        client = bigquery.Client(project=PROJECT_ID)
        start_time = datetime.datetime.now()
        query_job = client.query(query)
        results = query_job.result()
        duration_sec = (datetime.datetime.now() - start_time).total_seconds()

        columns = [field.name for field in results.schema] if results.schema else []
        rows = []
        for row in results:
            row_dict = {}
            for k, v in row.items():
                if isinstance(v, (datetime.date, datetime.datetime, datetime.time)):
                    row_dict[k] = v.isoformat()
                elif hasattr(v, "to_api_repr"):
                    row_dict[k] = v.to_api_repr()
                else:
                    row_dict[k] = v
            rows.append(row_dict)

        return {
            "status": "SUCCESS",
            "user_id": user_slug,
            "row_count": len(rows),
            "columns": columns,
            "data": rows,
            "execution_seconds": round(duration_sec, 2),
        }
    except Exception as e:
        logger.error(f"BigQuery execution failed: {e}")
        return {"status": "ERROR", "error": str(e), "query": query}
