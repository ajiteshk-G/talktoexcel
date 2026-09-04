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

"""ADK Plugin and Sanitizer for In-Chat Excel Spreadsheets.

Gemini foundation models do not natively support Excel spreadsheets
(application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, .xls, .xlsm)
as multimodal prompt parts, throwing:
  400 INVALID_ARGUMENT: Unable to submit request because it has a mimeType parameter
  with value application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, which is not supported.

This module intercepts incoming spreadsheet files from Gemini Enterprise chat,
uploads them into the user's isolated GCS directory:
  gs://{DROPZONE_BUCKET}/{user_id}/{filename}
flattens them into BigQuery ephemeral tables:
  mb-poc-352009.adhoc_excel_analytics.wb_{user_id}_{sheet} (2-Hour TTL)
and substitutes the unsupported binary Part with an informative text prompt
containing table names, schemas, and preview rows for the Agent to query.
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.cloud import storage
from google.genai import types

from app.ingestion import (
    DATASET_ID,
    DEFAULT_TTL_HOURS,
    DROPZONE_BUCKET,
    PROJECT_ID,
    find_blob_in_dropzone,
    ingest_file,
    normalize_spreadsheet_filename,
    sanitize_user_id,
    upload_bytes_to_dropzone,
)

logger = logging.getLogger("google_adk." + __name__)

SPREADSHEET_EXTENSIONS = {".xlsx", ".xls", ".xlsm", ".xlsb", ".ods", ".csv", ".tsv"}
SPREADSHEET_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/vnd.ms-excel.sheet.macroenabled.12",
    "application/vnd.ms-excel.sheet.binary.macroenabled.12",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/wps-office.xlsx",
    "application/wps-office.xls",
    "application/excel",
    "application/x-excel",
    "application/x-msexcel",
    "text/csv",
    "text/tab-separated-values",
    "application/csv",
}


def is_spreadsheet_mime(mime_type: Optional[str], filename: Optional[str] = None) -> bool:
    """Checks whether a MIME type or filename indicates a spreadsheet."""
    if mime_type:
        m = mime_type.lower().strip()
        if m in SPREADSHEET_MIME_TYPES or "spreadsheet" in m or "excel" in m or "sheet" in m:
            return True
    if filename:
        ext = os.path.splitext(filename.lower())[1]
        if ext in SPREADSHEET_EXTENSIONS:
            return True
    return False


def is_spreadsheet_part(part: types.Part) -> bool:
    """Checks if an ADK/GenAI Part holds a spreadsheet file."""
    mime_type = None
    filename = None
    if part.inline_data:
        mime_type = getattr(part.inline_data, "mime_type", None)
        filename = getattr(part.inline_data, "display_name", None)
    elif part.file_data:
        mime_type = getattr(part.file_data, "mime_type", None)
        filename = getattr(part.file_data, "display_name", None) or getattr(
            part.file_data, "file_uri", None
        )

    return is_spreadsheet_mime(mime_type, filename)


def extract_part_bytes_and_name(part: types.Part) -> Tuple[Optional[bytes], str]:
    """Extracts raw bytes and display filename from an ADK Part."""
    filename = "uploaded_spreadsheet.xlsx"
    file_bytes = None

    if part.inline_data:
        if part.inline_data.display_name:
            filename = part.inline_data.display_name
        data = part.inline_data.data
        if isinstance(data, str):
            try:
                file_bytes = base64.b64decode(data)
            except Exception:
                file_bytes = data.encode("utf-8")
        elif isinstance(data, (bytes, bytearray)):
            file_bytes = bytes(data)

    elif part.file_data:
        if part.file_data.display_name:
            filename = part.file_data.display_name
        uri = part.file_data.file_uri
        if uri:
            if not filename or filename == "uploaded_spreadsheet.xlsx":
                filename = uri.split("/")[-1] or filename
            if uri.startswith("gs://"):
                try:
                    storage_client = storage.Client(project=PROJECT_ID)
                    path = uri[5:]
                    b_name, o_name = path.split("/", 1)
                    file_bytes = storage_client.bucket(b_name).blob(o_name).download_as_bytes()
                except Exception as e:
                    logger.error(f"Error downloading GCS blob {uri}: {e}")
            elif uri.startswith("http://") or uri.startswith("https://"):
                try:
                    import httpx

                    resp = httpx.get(uri, timeout=30.0)
                    file_bytes = resp.content
                except Exception as e:
                    logger.error(f"Error downloading HTTP URI {uri}: {e}")

    # Ensure a proper file extension
    ext = os.path.splitext(filename)[1].lower()
    if not ext or ext not in SPREADSHEET_EXTENSIONS:
        filename = f"{filename}.xlsx"

    return file_bytes, filename


def process_and_ingest_spreadsheet(
    file_bytes: bytes, filename: str, user_id: str
) -> str:
    """Saves the file to user's isolated GCS path, flattens to BigQuery,

    and returns a structured text notification for the model.
    """
    user_slug = sanitize_user_id(user_id)
    clean_filename = os.path.basename(filename)

    try:
        # 1. Upload to GCS dropzone: gs://{DROPZONE_BUCKET}/{user_slug}/{clean_filename}
        gcs_uri = upload_bytes_to_dropzone(
            file_bytes=file_bytes,
            filename=clean_filename,
            user_id=user_slug,
            bucket_name=DROPZONE_BUCKET,
        )

        # 2. Ingest into BigQuery with 2-hour TTL
        ingest_result = ingest_file(
            file_path_or_uri=gcs_uri,
            user_id=user_slug,
            original_filename=clean_filename,
            ttl_hours=DEFAULT_TTL_HOURS,
        )

        if ingest_result.get("status") == "SUCCESS":
            sheets = ingest_result.get("sheets", [])
            sheet_summaries = []
            for s in sheets:
                tbl = s.get("table_name")
                s_name = s.get("sheet_name")
                cnt = s.get("row_count", 0)
                cols = [c["name"] for c in s.get("columns_schema", [])]
                preview = s.get("sample_preview", [])
                sheet_summaries.append(
                    f"  * Table: `{tbl}` (Sheet: '{s_name}', Rows: {cnt:,}, Columns: {cols})\n"
                    f"    Sample preview: {preview[:2]}"
                )

            tables_desc = "\n".join(sheet_summaries)
            return (
                f"[System Notification: The user uploaded spreadsheet '{clean_filename}' ({len(file_bytes):,} bytes).\n"
                f"Dropzone Path: {gcs_uri}\n"
                f"BigQuery Dataset: {PROJECT_ID}.{DATASET_ID} (Ephemeral 2-Hour TTL)\n"
                f"Generated Tables:\n{tables_desc}\n\n"
                f"INSTRUCTIONS FOR AGENT: The spreadsheet has been successfully parsed and flattened into BigQuery. "
                f"Acknowledge the upload to the user, state the table and column names, and answer any analytical "
                f"questions by querying these tables using the `run_analytical_query` tool.]"
            )
        else:
            err = ingest_result.get("error", "Unknown ingestion error")
            return (
                f"[System Notification: The user uploaded spreadsheet '{clean_filename}', but ingestion failed: {err}. "
                f"Please inform the user of this error.]"
            )

    except Exception as e:
        logger.exception(f"Failed to process and ingest spreadsheet {clean_filename}: {e}")
        return (
            f"[System Notification: An error occurred while processing uploaded spreadsheet '{clean_filename}': {e}. "
            f"Please inform the user.]"
        )


GE_START_TAG_REGEX = re.compile(
    r"<start_of_user_uploaded_file:\s*([^,>]+)(?:,\s*original_filename:\s*([^,>]+))?(?:,\s*sheet_name:\s*([^,>]+))?>",
    re.IGNORECASE,
)
GE_END_TAG_REGEX = re.compile(
    r"<end_of_user_uploaded_file:[^>]*>",
    re.IGNORECASE,
)


def build_ge_ingestion_notification(raw_filename: str, user_id: str) -> str:
    """Finds and ingests a spreadsheet identified by GE tag, returning the system notification."""
    clean_filename = normalize_spreadsheet_filename(raw_filename)
    user_slug = sanitize_user_id(user_id)

    blob = find_blob_in_dropzone(clean_filename, user_id=user_slug)
    if blob and (blob.size or 0) > 100:
        gcs_uri = f"gs://{DROPZONE_BUCKET}/{blob.name}"
        ingest_result = ingest_file(
            file_path_or_uri=gcs_uri,
            user_id=user_slug,
            original_filename=clean_filename,
            ttl_hours=DEFAULT_TTL_HOURS,
        )
        if ingest_result.get("status") == "SUCCESS":
            sheets = ingest_result.get("sheets", [])
            sheet_summaries = []
            for s in sheets:
                tbl = s.get("table_name")
                s_name = s.get("sheet_name")
                cnt = s.get("row_count", 0)
                cols = s.get("columns", [])
                sheet_summaries.append(
                    f"  * Table: `{tbl}` (Sheet: '{s_name}', Rows: {cnt:,}, Columns: {cols})"
                )
            tables_desc = "\n".join(sheet_summaries)
            return (
                f"\n[System Notification: The user uploaded spreadsheet '{clean_filename}' ({blob.size:,} bytes).\n"
                f"Dropzone Path: {gcs_uri}\n"
                f"BigQuery Dataset: {PROJECT_ID}.{DATASET_ID} (Ephemeral 2-Hour TTL)\n"
                f"Generated Tables:\n{tables_desc}\n\n"
                f"INSTRUCTIONS FOR AGENT: The spreadsheet has been successfully parsed and flattened into BigQuery. "
                f"Acknowledge the upload to the user, state the table and column names, and answer any analytical "
                f"questions by querying these tables using the `run_analytical_query` tool. "
                f"NEVER attempt to load raw data with load_artifacts—query BigQuery instead.]\n"
            )
        else:
            err = ingest_result.get("error", "Unknown ingestion error")
            return f"\n[System Notification: The user uploaded spreadsheet '{clean_filename}', but ingestion failed: {err}. Please inform the user.]\n"
    else:
        return (
            f"\n[System Notification: The user referenced spreadsheet '{clean_filename}'. "
            f"Please check available tables with `list_available_spreadsheets` or files with `list_dropzone_files`.]\n"
        )


def process_ge_text_tags(text: str, user_id: str) -> Tuple[str, bool]:
    """Inspects text for Gemini Enterprise <start_of_user_uploaded_file:...> tags.

    If found, dynamically resolves the spreadsheet from GCS dropzone, flattens to BigQuery,
    and replaces the tag with a structured system grounding notification.
    """
    if not text or "<start_of_user_uploaded_file:" not in text:
        return text, False

    match = GE_START_TAG_REGEX.search(text)
    if not match:
        return text, False

    orig_fname = match.group(2)
    fallback_fname = match.group(1)
    raw_filename = (orig_fname or fallback_fname or "uploaded_spreadsheet.xlsx").strip()
    notif = build_ge_ingestion_notification(raw_filename, user_id)

    # Strip start and end tags
    replaced_text = GE_START_TAG_REGEX.sub(notif, text)
    replaced_text = GE_END_TAG_REGEX.sub("", replaced_text).strip()
    return replaced_text, True


def sanitize_part(part: types.Part, user_id: str) -> Tuple[types.Part, bool]:
    """Inspects a Part and replaces spreadsheet content with ingested table text."""
    if part.text and "<start_of_user_uploaded_file:" in part.text:
        new_text, changed = process_ge_text_tags(part.text, user_id)
        if changed:
            return types.Part.from_text(text=new_text), True

    if not is_spreadsheet_part(part):
        return part, False

    file_bytes, filename = extract_part_bytes_and_name(part)
    if file_bytes:
        notification = process_and_ingest_spreadsheet(
            file_bytes=file_bytes, filename=filename, user_id=user_id
        )
    else:
        notification = (
            f"[System Notification: The user uploaded spreadsheet '{filename}', but the binary payload could not be extracted. "
            f"Please ask the user to re-upload the file.]"
        )

    return types.Part.from_text(text=notification), True


def sanitize_content(content: types.Content, user_id: str) -> Tuple[types.Content, bool]:
    """Sanitizes all parts in a types.Content object, supporting single-part and multi-part GE tags."""
    if not content.parts:
        return content, False

    user_slug = sanitize_user_id(user_id)
    modified = False
    new_parts: List[types.Part] = []

    for part in content.parts:
        # Binary spreadsheet part
        if is_spreadsheet_part(part):
            file_bytes, filename = extract_part_bytes_and_name(part)
            if file_bytes:
                notif = process_and_ingest_spreadsheet(
                    file_bytes=file_bytes, filename=filename, user_id=user_slug
                )
            else:
                notif = (
                    f"[System Notification: The user uploaded spreadsheet '{filename}', but the binary payload could not be extracted. "
                    f"Please ask the user to re-upload the file.]"
                )
            new_parts.append(types.Part.from_text(text=notif))
            modified = True
            continue

        # Text part with GE tags
        if part.text and ("<start_of_user_uploaded_file:" in part.text or "<end_of_user_uploaded_file:" in part.text):
            text = part.text
            if "<start_of_user_uploaded_file:" in text:
                for match in GE_START_TAG_REGEX.finditer(text):
                    orig_fname = match.group(2)
                    fallback_fname = match.group(1)
                    raw_filename = (orig_fname or fallback_fname or "uploaded_spreadsheet.xlsx").strip()
                    notif = build_ge_ingestion_notification(raw_filename, user_slug)
                    text = GE_START_TAG_REGEX.sub(notif, text)
            text = GE_END_TAG_REGEX.sub("", text).strip()
            if text:
                new_parts.append(types.Part.from_text(text=text))
            modified = True
            continue

        new_parts.append(part)

    if modified:
        return types.Content(role=content.role, parts=new_parts), True
    return content, False


def sanitize_message_dict(message_dict_or_str: Any, user_id: str) -> Any:
    """Sanitizes a raw JSON message dict (from reasoning_engine or ADK API HTTP ingress)
    replacing any inlineData/fileData spreadsheets and multi-part GE text tags with ingested table notifications.
    """
    if not isinstance(message_dict_or_str, dict):
        return message_dict_or_str

    parts = message_dict_or_str.get("parts")
    if not isinstance(parts, list):
        return message_dict_or_str

    user_slug = sanitize_user_id(user_id)
    new_parts = []

    for p in parts:
        if not isinstance(p, dict):
            new_parts.append(p)
            continue

        # Check for GE text tags
        if "text" in p and isinstance(p["text"], str) and (
            "<start_of_user_uploaded_file:" in p["text"] or "<end_of_user_uploaded_file:" in p["text"]
        ):
            text = p["text"]
            if "<start_of_user_uploaded_file:" in text:
                for match in GE_START_TAG_REGEX.finditer(text):
                    orig_fname = match.group(2)
                    fallback_fname = match.group(1)
                    raw_filename = (orig_fname or fallback_fname or "uploaded_spreadsheet.xlsx").strip()
                    notif = build_ge_ingestion_notification(raw_filename, user_slug)
                    text = GE_START_TAG_REGEX.sub(notif, text)
            text = GE_END_TAG_REGEX.sub("", text).strip()
            if text:
                new_parts.append({"text": text})
            continue

        # Check inlineData / inline_data
        inline_data = p.get("inlineData") or p.get("inline_data")
        file_data = p.get("fileData") or p.get("file_data")

        mime_type = None
        display_name = None
        data = None
        file_uri = None

        if isinstance(inline_data, dict):
            mime_type = inline_data.get("mimeType") or inline_data.get("mime_type")
            display_name = inline_data.get("displayName") or inline_data.get("display_name")
            data = inline_data.get("data")
        elif isinstance(file_data, dict):
            mime_type = file_data.get("mimeType") or file_data.get("mime_type")
            display_name = file_data.get("displayName") or file_data.get("display_name")
            file_uri = file_data.get("fileUri") or file_data.get("file_uri")

        if is_spreadsheet_mime(mime_type, display_name or file_uri):
            filename = display_name or "uploaded_spreadsheet.xlsx"
            file_bytes = None
            if data:
                if isinstance(data, str):
                    try:
                        file_bytes = base64.b64decode(data)
                    except Exception:
                        file_bytes = data.encode("utf-8")
                elif isinstance(data, (bytes, bytearray)):
                    file_bytes = bytes(data)
            elif file_uri and file_uri.startswith("gs://"):
                try:
                    storage_client = storage.Client(project=PROJECT_ID)
                    path = file_uri[5:]
                    b_name, o_name = path.split("/", 1)
                    file_bytes = storage_client.bucket(b_name).blob(o_name).download_as_bytes()
                except Exception as e:
                    logger.error(f"Error downloading GCS URI {file_uri}: {e}")

            if file_bytes:
                text_notif = process_and_ingest_spreadsheet(
                    file_bytes=file_bytes, filename=filename, user_id=user_slug
                )
            else:
                text_notif = (
                    f"[System Notification: The user uploaded spreadsheet '{filename}', but binary content could not be read. "
                    f"Please ask the user to re-upload.]"
                )

            new_parts.append({"text": text_notif})
        else:
            new_parts.append(p)

    return {**message_dict_or_str, "parts": new_parts}


class ExcelSpreadsheetIngestionPlugin(BasePlugin):
    """ADK Plugin that intercepts user-uploaded Excel spreadsheets in chat,
    automatically uploads them to GCS dropzone, flattens them into BigQuery
    with a 2-hour TTL, and replaces the unsupported MIME type with a text
    prompt grounding the model in the ingested table schemas.
    """

    def __init__(self, name: str = "excel_spreadsheet_ingestion_plugin"):
        super().__init__(name)

    async def on_user_message_callback(
        self,
        *,
        invocation_context: InvocationContext,
        user_message: types.Content,
    ) -> Optional[types.Content]:
        """Intercepts user messages before the runner processes them."""
        user_id = sanitize_user_id(invocation_context.user_id)
        sanitized_content, modified = sanitize_content(user_message, user_id)
        if modified:
            logger.info(f"ExcelSpreadsheetIngestionPlugin sanitized user message for user: {user_id}")
            return sanitized_content
        return None

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> Optional[LlmResponse]:
        """Safety net: ensures llm_request.contents NEVER contains an unsupported
        spreadsheet MIME type or raw GE upload tags when calling Vertex AI Gemini.
        """
        user_id = sanitize_user_id(callback_context.user_id)
        if not llm_request.contents:
            return None

        for i, content in enumerate(llm_request.contents):
            new_content, changed = sanitize_content(content, user_id)
            if changed:
                llm_request.contents[i] = new_content
                logger.info(f"before_model_callback sanitized content for user: {user_id}")

        return None


async def before_model_callback_hook(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> Optional[LlmResponse]:
    """Direct agent-level before_model_callback hook for root_agent."""
    user_id = sanitize_user_id(callback_context.user_id)
    if not llm_request.contents:
        return None

    for i, content in enumerate(llm_request.contents):
        new_content, changed = sanitize_content(content, user_id)
        if changed:
            llm_request.contents[i] = new_content
            logger.info(
                f"Agent before_model_callback replaced spreadsheet content with text for {user_id}"
            )

    return None
