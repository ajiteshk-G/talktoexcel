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

"""Spreadsheet ingestion engine for Excel (.xlsx, .xls, .xlsm) and CSV files into BigQuery.

Multi-Tenant User Isolation Features:
- Files land in isolated user directories in GCS: gs://{bucket}/{user_id}/{filename}
- Ephemeral BigQuery tables scoped by user: wb_{user_id}_{sheet}
- Registry & metadata filtered by user_id
- 2-hour TTL table expiration
- Calamine + Polars Parquet ingestion
"""

import base64
import csv
import datetime
import io
import json
import logging
import os
import re
import tempfile
import uuid
from typing import Any, Dict, List, Optional, Tuple

from google.cloud import bigquery
from google.cloud import storage
import polars as pl
import python_calamine

os.environ.setdefault("GOOGLE_API_USE_CLIENT_CERTIFICATE", "false")

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "mb-poc-352009")
DATASET_ID = os.environ.get("BQ_DATASET", "adhoc_excel_analytics")
DROPZONE_BUCKET = os.environ.get("GCS_DROPZONE_BUCKET", "mb-poc-352009-excel-dropzone")
DEFAULT_TTL_HOURS = 2


DEFAULT_USER_ID = os.environ.get("DEFAULT_USER_ID", "default_user")


def sanitize_user_id(user_id: Optional[str]) -> str:
    """Sanitizes caller identifier into a clean, safe identifier for paths and metadata.

    Falls back to configured DEFAULT_USER_ID if empty or generic placeholder.
    Contains ZERO hardcoded user names, emails, or domains.
    """
    if not user_id:
        return DEFAULT_USER_ID

    uid_str = str(user_id).strip()
    if uid_str.lower() in {"user", "default_user", "none", "unknown", "null", ""}:
        return DEFAULT_USER_ID

    # Clean characters safe for GCS folder names and metadata
    clean = re.sub(r"[^a-zA-Z0-9_@.-]", "_", uid_str).strip()
    return clean or DEFAULT_USER_ID


def sanitize_user_id_for_bq(user_id: Optional[str]) -> str:
    """Sanitizes user identifier into a valid BigQuery identifier ([a-zA-Z0-9_]).

    Contains ZERO hardcoded user names, emails, or domains.
    """
    canonical = sanitize_user_id(user_id)
    if "@" in canonical:
        local_part, domain_part = canonical.split("@", 1)
        base = f"{local_part}_{domain_part.split('.')[0]}"
    else:
        base = canonical
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", base).lower()
    clean = re.sub(r"_+", "_", clean).strip("_")
    if not clean:
        clean = "user"
    if clean[0].isdigit():
        clean = f"u_{clean}"
    return clean[:20]


def normalize_spreadsheet_filename(filename: str) -> str:
    """Strips GE sheet suffixes like _Sheet1_Sheet1.csv or _Sheet1.csv from spreadsheet filenames."""
    clean = os.path.basename(filename)
    stripped = re.sub(r"_[Ss]heet[0-9a-zA-Z_]*\.csv$", ".xlsx", clean, flags=re.IGNORECASE)
    if stripped != clean:
        return stripped
    return clean


def find_blob_in_dropzone(
    filename_or_uri: str,
    user_id: Optional[str] = None,
    bucket_name: str = DROPZONE_BUCKET,
) -> Optional[storage.Blob]:
    """Dynamically finds a blob in the dropzone bucket with ZERO hardcoding:
    1. If a direct gs:// URI is given, checks if that blob exists.
    2. Checks user-specific folder: gs://{bucket}/{user_id}/{filename}
    3. Checks root of bucket: gs://{bucket}/{filename}
    4. Searches all blobs in the dropzone bucket for a matching filename (size > 100 bytes).
    """
    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(bucket_name)

    if filename_or_uri.startswith("gs://"):
        path_without_scheme = filename_or_uri[5:]
        parts = path_without_scheme.split("/", 1)
        b_name = parts[0]
        blob_path = parts[1] if len(parts) > 1 else ""
        if b_name == bucket_name:
            b = bucket.blob(blob_path)
            if b.exists() and (b.size or 0) > 100:
                return b
        filename_or_uri = os.path.basename(blob_path)

    clean_filename = os.path.basename(filename_or_uri)
    candidates = [clean_filename]
    norm_name = normalize_spreadsheet_filename(clean_filename)
    if norm_name not in candidates:
        candidates.append(norm_name)

    if clean_filename.lower().endswith(".csv"):
        base_no_ext = os.path.splitext(clean_filename)[0]
        candidates.append(f"{base_no_ext}.xlsx")
    elif clean_filename.lower().endswith(".xlsx"):
        base_no_ext = os.path.splitext(clean_filename)[0]
        candidates.append(f"{base_no_ext}.csv")

    # Check user-specific folder if user_id is provided
    if user_id:
        user_slug = sanitize_user_id(user_id)
        for fname in candidates:
            b = bucket.blob(f"{user_slug}/{fname}")
            if b.exists() and (b.size or 0) > 100:
                return b

    # Check root of dropzone bucket
    for fname in candidates:
        b = bucket.blob(fname)
        if b.exists() and (b.size or 0) > 100:
            return b

    # Dynamic search across dropzone bucket for matching filename
    try:
        blobs = list(storage_client.list_blobs(bucket, max_results=200))
        for fname in candidates:
            fname_lower = fname.lower()
            for b in blobs:
                if (b.size or 0) <= 100:
                    continue
                b_name_lower = b.name.lower()
                b_base = os.path.basename(b.name).lower()
                # 1. Direct basename match
                if b_base == fname_lower:
                    return b
                # 2. ADK artifact path with version suffix /0 (e.g. app/.../filename/0)
                if b_base.isdigit():
                    parent_part = b.name.rstrip("/0123456789").split("/")[-1].lower()
                    if parent_part == fname_lower or parent_part.startswith(fname_lower):
                        return b
                # 3. Filename contained as path segment
                if f"/{fname_lower}/" in f"/{b_name_lower}/" or f"/{fname_lower}" in b_name_lower:
                    return b
    except Exception as e:
        logger.warning(f"Dropzone search encountered error: {e}")

    return None


def sanitize_column_name(raw_name: Any, index: int, seen: Dict[str, int]) -> str:
    """Sanitizes a column header into a compliant BigQuery column identifier."""
    raw_str = str(raw_name).strip() if raw_name is not None else ""
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", raw_str).strip("_")
    clean = re.sub(r"_+", "_", clean).lower()

    if not clean or clean[0].isdigit():
        clean = f"col_{clean}" if clean else f"col_{index + 1}"

    clean = clean[:128]

    if clean in seen:
        seen[clean] += 1
        clean = f"{clean}_{seen[clean]}"
    else:
        seen[clean] = 0

    return clean


def sanitize_headers(headers: List[Any]) -> List[str]:
    """Sanitizes a list of raw column headers."""
    seen: Dict[str, int] = {}
    return [sanitize_column_name(h, i, seen) for i, h in enumerate(headers)]


def generate_workbook_id(filename: str, user_id: str = "default_user") -> str:
    """Generates a unique, user-scoped BigQuery-safe identifier for the workbook."""
    user_slug = sanitize_user_id_for_bq(user_id)
    base = os.path.basename(filename).split(".")[0]
    slug = re.sub(r"[^a-zA-Z0-9]", "_", base).strip("_").lower()[:12]
    if not slug:
        slug = "sheet"
    short_uid = uuid.uuid4().hex[:6]
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"wb_{user_slug}_{slug}_{timestamp}_{short_uid}"


def generate_table_name(workbook_id: str, sheet_name: str) -> str:
    """Generates a BigQuery-safe table name for a sheet within a workbook."""
    sheet_slug = re.sub(r"[^a-zA-Z0-9]", "_", sheet_name).strip("_").lower()[:20]
    if not sheet_slug:
        sheet_slug = "data"
    return f"{workbook_id}_{sheet_slug}"


def upload_bytes_to_dropzone(
    file_bytes: bytes,
    filename: str,
    user_id: str = "default_user",
    bucket_name: str = DROPZONE_BUCKET,
) -> str:
    """Uploads file bytes directly to the user's isolated GCS directory:

    gs://{bucket_name}/{user_id_slug}/{clean_filename}
    """
    user_slug = sanitize_user_id(user_id)
    clean_filename = os.path.basename(filename)
    blob_name = f"{user_slug}/{clean_filename}"

    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(file_bytes)
    logger.info(f"Uploaded file to user-isolated path: gs://{bucket_name}/{blob_name}")
    return f"gs://{bucket_name}/{blob_name}"


def upload_user_artifact_to_gcs(
    user_id: str,
    subfolder: str,
    filename: str,
    data_bytes: bytes,
    content_type: str = "application/octet-stream",
    bucket_name: str = DROPZONE_BUCKET,
) -> Tuple[str, str]:
    """Uploads an artifact (chart, creative, report) to user-isolated path:
    gs://{bucket_name}/{user_slug}/{subfolder}/{filename}
    Returns (gcs_uri, web_url).
    """
    user_slug = sanitize_user_id(user_id)
    clean_subfolder = subfolder.strip("/")
    clean_filename = os.path.basename(filename)
    blob_name = f"{user_slug}/{clean_subfolder}/{clean_filename}" if clean_subfolder else f"{user_slug}/{clean_filename}"

    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(data_bytes, content_type=content_type)
    gcs_uri = f"gs://{bucket_name}/{blob_name}"
    web_url = f"https://storage.googleapis.com/{bucket_name}/{blob_name}"
    logger.info(f"Uploaded user artifact to: {gcs_uri}")
    return gcs_uri, web_url


def download_from_gcs(gcs_uri: str, local_dest: str, user_id: Optional[str] = None) -> None:
    """Downloads a file from Google Cloud Storage to a local destination."""
    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"Invalid GCS URI: {gcs_uri}")
    path_without_scheme = gcs_uri[5:]
    parts = path_without_scheme.split("/", 1)
    bucket_name = parts[0]
    blob_name = parts[1] if len(parts) > 1 else ""

    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    if not blob.exists() or (blob.size or 0) <= 100:
        fallback_blob = find_blob_in_dropzone(blob_name, user_id=user_id, bucket_name=bucket_name)
        if fallback_blob:
            blob = fallback_blob
        else:
            raise FileNotFoundError(f"Blob not found in GCS: {gcs_uri}")
    blob.download_to_filename(local_dest)


def list_dropzone_files(
    user_id: Optional[str] = None,
    bucket_name: str = DROPZONE_BUCKET,
    max_results: int = 50,
) -> List[Dict[str, Any]]:
    """Lists files in the dropzone bucket for the user and dropzone root without hardcoding."""
    try:
        storage_client = storage.Client(project=PROJECT_ID)
        bucket = storage_client.bucket(bucket_name)
        user_slug = sanitize_user_id(user_id)

        results = []
        seen_filenames = set()

        # Prefixes to scan: user-specific folder and bucket root
        prefixes = [f"{user_slug}/", ""]

        for prefix in prefixes:
            blobs = list(storage_client.list_blobs(bucket, prefix=prefix or None, max_results=max_results))
            for b in sorted(blobs, key=lambda x: x.updated or datetime.datetime.min, reverse=True):
                if not b.name.endswith("/") and (b.size or 0) > 100:
                    raw_filename = b.name[len(prefix):] if prefix and b.name.startswith(prefix) else os.path.basename(b.name)
                    # Skip artifact subfolders (charts, creatives, reports)
                    if "/" in raw_filename:
                        continue
                    if raw_filename not in seen_filenames:
                        seen_filenames.add(raw_filename)
                        results.append({
                            "filename": raw_filename,
                            "gcs_uri": f"gs://{bucket_name}/{b.name}",
                            "size_bytes": b.size,
                            "updated": b.updated.isoformat() if b.updated else None,
                            "user_id": user_slug,
                        })
        return results
    except Exception as e:
        logger.error(f"Error listing dropzone files for user {user_id}: {e}")
        return []


def parse_excel_to_dataframes(file_path: str) -> Dict[str, pl.DataFrame]:
    """Parses all sheets in an Excel workbook into Polars DataFrames with sanitized headers."""
    cwb = python_calamine.load_workbook(file_path)
    sheet_dfs: Dict[str, pl.DataFrame] = {}

    for sheet_name in cwb.sheet_names:
        sheet = cwb.get_sheet_by_name(sheet_name)
        raw_rows = sheet.to_python()
        if not raw_rows:
            continue

        header_row_idx = 0
        while header_row_idx < len(raw_rows) and not any(raw_rows[header_row_idx]):
            header_row_idx += 1

        if header_row_idx >= len(raw_rows):
            continue

        raw_headers = raw_rows[header_row_idx]
        cleaned_headers = sanitize_headers(raw_headers)
        data_rows = raw_rows[header_row_idx + 1:]

        if not data_rows:
            sheet_dfs[sheet_name] = pl.DataFrame({h: [] for h in cleaned_headers})
            continue

        num_cols = len(cleaned_headers)
        col_data: Dict[str, list] = {h: [] for h in cleaned_headers}
        for row in data_rows:
            for col_idx in range(num_cols):
                val = row[col_idx] if col_idx < len(row) else None
                if isinstance(val, datetime.time):
                    val = val.strftime("%H:%M:%S")
                col_data[cleaned_headers[col_idx]].append(val)

        df = pl.DataFrame(col_data, strict=False)
        sheet_dfs[sheet_name] = df

    return sheet_dfs


def parse_csv_to_dataframes(file_path: str, filename: str) -> Dict[str, pl.DataFrame]:
    """Parses a CSV file into a Polars DataFrame with sanitized headers."""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        raw_headers = next(reader, [])
    cleaned_headers = sanitize_headers(raw_headers)

    df = pl.read_csv(
        file_path,
        has_header=True,
        new_columns=cleaned_headers,
        ignore_errors=True,
        infer_schema_length=10000,
    )
    base_name = os.path.splitext(os.path.basename(filename))[0]
    return {base_name: df}


def load_sheet_to_bigquery(
    client: bigquery.Client,
    df: pl.DataFrame,
    table_id: str,
    ttl_hours: int = DEFAULT_TTL_HOURS,
) -> Tuple[int, List[Dict[str, str]], List[Dict[str, Any]]]:
    """Loads a Polars DataFrame as Parquet into BigQuery and configures table TTL expiration."""
    buf = io.BytesIO()
    df.write_parquet(buf)
    buf.seek(0)

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )

    job = client.load_table_from_file(buf, table_id, job_config=job_config)
    job.result()

    table = client.get_table(table_id)
    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=ttl_hours)
    table.expires = expires_at
    client.update_table(table, ["expires"])

    columns_schema = [{"name": f.name, "type": f.field_type} for f in table.schema]
    sample_rows = [dict(row) for row in df.head(3).to_dicts()]

    return table.num_rows, columns_schema, sample_rows


def record_metadata(
    client: bigquery.Client,
    workbook_id: str,
    user_id: str,
    original_filename: str,
    gcs_uri: str,
    sheets_info: List[Dict[str, Any]],
    ttl_hours: int = DEFAULT_TTL_HOURS,
) -> None:
    """Records ingestion metadata in per-workbook metadata table and global registry with user isolation."""
    metadata_table_id = f"{PROJECT_ID}.{DATASET_ID}.{workbook_id}__metadata"
    registry_table_id = f"{PROJECT_ID}.{DATASET_ID}.excel_files_registry"

    expires_at = (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=ttl_hours)
    ).isoformat()
    now_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    user_slug = sanitize_user_id(user_id)

    rows_to_insert = []
    for s in sheets_info:
        rows_to_insert.append({
            "workbook_id": workbook_id,
            "user_id": user_slug,
            "original_filename": original_filename,
            "gcs_uri": gcs_uri,
            "sheet_name": s["sheet_name"],
            "table_name": s["table_name"],
            "full_table_id": s["full_table_id"],
            "row_count": int(s["row_count"]),
            "column_count": int(s["column_count"]),
            "columns_schema": json.dumps(s["columns_schema"]),
            "sample_preview": json.dumps(s["sample_preview"], default=str),
            "ingested_at": now_ts,
            "expires_at": expires_at,
        })

    schema = [
        bigquery.SchemaField("workbook_id", "STRING"),
        bigquery.SchemaField("user_id", "STRING"),
        bigquery.SchemaField("original_filename", "STRING"),
        bigquery.SchemaField("gcs_uri", "STRING"),
        bigquery.SchemaField("sheet_name", "STRING"),
        bigquery.SchemaField("table_name", "STRING"),
        bigquery.SchemaField("full_table_id", "STRING"),
        bigquery.SchemaField("row_count", "INTEGER"),
        bigquery.SchemaField("column_count", "INTEGER"),
        bigquery.SchemaField("columns_schema", "STRING"),
        bigquery.SchemaField("sample_preview", "STRING"),
        bigquery.SchemaField("ingested_at", "TIMESTAMP"),
        bigquery.SchemaField("expires_at", "TIMESTAMP"),
    ]

    # 1. Per-workbook metadata table with ephemeral TTL
    table = bigquery.Table(metadata_table_id, schema=schema)
    table.expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=ttl_hours)
    client.create_table(table, exists_ok=True)
    client.insert_rows_json(metadata_table_id, rows_to_insert)

    # 2. Global registry table (create or alter to add user_id column if needed)
    reg_table = bigquery.Table(registry_table_id, schema=schema)
    try:
        client.create_table(reg_table, exists_ok=True)
    except Exception:
        pass
    client.insert_rows_json(registry_table_id, rows_to_insert)


def ingest_file(
    file_path_or_uri: str,
    user_id: str = "default_user",
    original_filename: Optional[str] = None,
    ttl_hours: int = DEFAULT_TTL_HOURS,
) -> Dict[str, Any]:
    """End-to-end ingestion pipeline with strict user directory isolation:

    Ensures files and tables belong exclusively to the specified user_id.
    """
    canonical_user = sanitize_user_id(user_id)
    user_bq_slug = sanitize_user_id_for_bq(user_id)
    is_gcs = file_path_or_uri.startswith("gs://")

    # Locate blob in dropzone across user aliases
    blob = None
    if is_gcs:
        blob = find_blob_in_dropzone(file_path_or_uri, user_id=canonical_user)
    elif not os.path.exists(file_path_or_uri):
        blob = find_blob_in_dropzone(file_path_or_uri, user_id=canonical_user)
        if blob:
            file_path_or_uri = f"gs://{DROPZONE_BUCKET}/{blob.name}"
            is_gcs = True

    if is_gcs and blob:
        file_path_or_uri = f"gs://{DROPZONE_BUCKET}/{blob.name}"

    filename = original_filename or (
        blob.name.split("/")[-1] if blob else (
            file_path_or_uri.split("/")[-1] if is_gcs else os.path.basename(file_path_or_uri)
        )
    )
    filename = normalize_spreadsheet_filename(filename)
    lower_filename = filename.lower()
    is_csv = lower_filename.endswith(".csv")

    temp_file = None
    try:
        if is_gcs:
            suffix = ".csv" if is_csv else ".xlsx"
            temp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            temp_file.close()
            download_from_gcs(file_path_or_uri, temp_file.name, user_id=canonical_user)
            local_path = temp_file.name
            gcs_uri = file_path_or_uri
        else:
            local_path = file_path_or_uri
            gcs_uri = f"gs://{DROPZONE_BUCKET}/{canonical_user}/{filename}"

        def _is_excel_binary(path: str) -> bool:
            try:
                with open(path, "rb") as f:
                    hdr = f.read(8)
                return hdr.startswith(b"PK\x03\x04") or hdr.startswith(b"\xd0\xcf\x11\xe0") or hdr.startswith(b"\x09\x08")
            except Exception:
                return False

        if _is_excel_binary(local_path):
            sheet_dfs = parse_excel_to_dataframes(local_path)
        else:
            sheet_dfs = parse_csv_to_dataframes(local_path, filename)

        if not sheet_dfs:
            return {
                "status": "FAILED",
                "error": "No valid data or sheets found in the provided spreadsheet.",
                "filename": filename,
                "user_id": canonical_user,
            }

        client = bigquery.Client(project=PROJECT_ID)
        workbook_id = generate_workbook_id(filename, user_id=user_bq_slug)
        sheets_info = []

        for sheet_name, df in sheet_dfs.items():
            tbl_name = generate_table_name(workbook_id, sheet_name)
            full_table_id = f"{PROJECT_ID}.{DATASET_ID}.{tbl_name}"
            row_count, cols_schema, sample_rows = load_sheet_to_bigquery(
                client=client,
                df=df,
                table_id=full_table_id,
                ttl_hours=ttl_hours,
            )
            sheets_info.append({
                "sheet_name": sheet_name,
                "table_name": tbl_name,
                "full_table_id": full_table_id,
                "row_count": row_count,
                "column_count": len(cols_schema),
                "columns_schema": cols_schema,
                "sample_preview": sample_rows,
            })

        record_metadata(
            client=client,
            workbook_id=workbook_id,
            user_id=canonical_user,
            original_filename=filename,
            gcs_uri=gcs_uri,
            sheets_info=sheets_info,
            ttl_hours=ttl_hours,
        )

        sheet_summaries = [
            {
                "sheet_name": s["sheet_name"],
                "table_name": s["table_name"],
                "full_table_id": s["full_table_id"],
                "row_count": s["row_count"],
                "columns": [c["name"] for c in s["columns_schema"]],
            }
            for s in sheets_info
        ]

        return {
            "status": "SUCCESS",
            "workbook_id": workbook_id,
            "user_id": canonical_user,
            "filename": filename,
            "gcs_uri": gcs_uri,
            "total_sheets": len(sheets_info),
            "sheets": sheet_summaries,
            "expiration_ttl_hours": ttl_hours,
            "message": (
                f"Successfully ingested '{filename}' for user '{canonical_user}' into BigQuery ({len(sheets_info)} sheets). "
                f"Tables are ready for querying and will expire in {ttl_hours} hours."
            ),
        }

    except Exception as e:
        logger.exception(f"Ingestion failed for {filename}: {e}")
        return {
            "status": "FAILED",
            "error": str(e),
            "filename": filename,
            "user_id": canonical_user,
        }
    finally:
        if temp_file and os.path.exists(temp_file.name):
            try:
                os.remove(temp_file.name)
            except Exception:
                pass
