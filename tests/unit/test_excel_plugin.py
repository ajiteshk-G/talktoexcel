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

import base64
import io
import openpyxl
import pytest
from unittest.mock import patch, MagicMock

from google.genai import types
from app.excel_plugin import (
    is_spreadsheet_mime,
    is_spreadsheet_part,
    extract_part_bytes_and_name,
    sanitize_part,
    sanitize_content,
    sanitize_message_dict,
    ExcelSpreadsheetIngestionPlugin,
    before_model_callback_hook,
)


@pytest.fixture
def sample_xlsx_bytes():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Financials"
    ws.append(["Category", "Budget", "Actual"])
    ws.append(["Payroll", 100000, 95000])
    ws.append(["Cloud", 20000, 18500])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_is_spreadsheet_mime():
    assert is_spreadsheet_mime("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert is_spreadsheet_mime("application/vnd.ms-excel")
    assert is_spreadsheet_mime("text/csv")
    assert is_spreadsheet_mime(None, "my_report.xlsx")
    assert is_spreadsheet_mime(None, "data.csv")
    assert not is_spreadsheet_mime("image/png", "photo.png")
    assert not is_spreadsheet_mime("application/pdf", "doc.pdf")


def test_is_spreadsheet_part(sample_xlsx_bytes):
    p_excel = types.Part.from_bytes(
        data=sample_xlsx_bytes,
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    p_text = types.Part.from_text(text="Hello world")
    assert is_spreadsheet_part(p_excel) is True
    assert is_spreadsheet_part(p_text) is False


def test_extract_part_bytes_and_name(sample_xlsx_bytes):
    p_excel = types.Part.from_bytes(
        data=sample_xlsx_bytes,
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    p_excel.inline_data.display_name = "q1_budget.xlsx"

    file_bytes, filename = extract_part_bytes_and_name(p_excel)
    assert file_bytes == sample_xlsx_bytes
    assert filename == "q1_budget.xlsx"


@patch("app.excel_plugin.upload_bytes_to_dropzone")
@patch("app.excel_plugin.ingest_file")
def test_sanitize_part(mock_ingest, mock_upload, sample_xlsx_bytes):
    mock_upload.return_value = "gs://dropzone/ajiteshk/q1_budget.xlsx"
    mock_ingest.return_value = {
        "status": "SUCCESS",
        "sheets": [
            {
                "sheet_name": "Financials",
                "table_name": "wb_ajiteshk_q1_budget_financials",
                "row_count": 2,
                "columns_schema": [{"name": "category", "type": "STRING"}],
                "sample_preview": [{"category": "Payroll"}],
            }
        ],
    }

    p_excel = types.Part.from_bytes(
        data=sample_xlsx_bytes,
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    p_excel.inline_data.display_name = "q1_budget.xlsx"

    sanitized_part, modified = sanitize_part(p_excel, user_id="ajiteshk")
    assert modified is True
    assert sanitized_part.inline_data is None
    assert sanitized_part.text is not None
    assert "wb_ajiteshk_q1_budget_financials" in sanitized_part.text
    assert "gs://dropzone/ajiteshk/q1_budget.xlsx" in sanitized_part.text


@patch("app.excel_plugin.upload_bytes_to_dropzone")
@patch("app.excel_plugin.ingest_file")
def test_sanitize_content(mock_ingest, mock_upload, sample_xlsx_bytes):
    mock_upload.return_value = "gs://dropzone/ajiteshk/budget.xlsx"
    mock_ingest.return_value = {
        "status": "SUCCESS",
        "sheets": [
            {
                "sheet_name": "Sheet1",
                "table_name": "wb_ajiteshk_budget_sheet1",
                "row_count": 5,
                "columns_schema": [{"name": "item", "type": "STRING"}],
                "sample_preview": [],
            }
        ],
    }

    content = types.Content(
        role="user",
        parts=[
            types.Part.from_bytes(
                data=sample_xlsx_bytes,
                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            types.Part.from_text(text="What is the total spend?"),
        ],
    )

    sanitized_content, modified = sanitize_content(content, user_id="ajiteshk")
    assert modified is True
    assert len(sanitized_content.parts) == 2
    # First part must be text (replaced excel)
    assert sanitized_content.parts[0].text is not None
    assert sanitized_content.parts[0].inline_data is None
    # Second part preserved
    assert sanitized_content.parts[1].text == "What is the total spend?"


@patch("app.excel_plugin.upload_bytes_to_dropzone")
@patch("app.excel_plugin.ingest_file")
def test_sanitize_message_dict(mock_ingest, mock_upload, sample_xlsx_bytes):
    mock_upload.return_value = "gs://dropzone/ajiteshk/uploaded.xlsx"
    mock_ingest.return_value = {
        "status": "SUCCESS",
        "sheets": [
            {
                "sheet_name": "Sheet1",
                "table_name": "wb_ajiteshk_uploaded_sheet1",
                "row_count": 10,
                "columns_schema": [{"name": "x", "type": "INT64"}],
                "sample_preview": [],
            }
        ],
    }

    b64 = base64.b64encode(sample_xlsx_bytes).decode("utf-8")
    msg_dict = {
        "role": "user",
        "parts": [
            {
                "inlineData": {
                    "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "data": b64,
                    "displayName": "uploaded.xlsx",
                }
            },
            {"text": "Analyze this file"},
        ],
    }

    sanitized = sanitize_message_dict(msg_dict, user_id="ajiteshk")
    assert len(sanitized["parts"]) == 2
    assert "inlineData" not in sanitized["parts"][0]
    assert "text" in sanitized["parts"][0]
    assert "wb_ajiteshk_uploaded_sheet1" in sanitized["parts"][0]["text"]
    assert sanitized["parts"][1]["text"] == "Analyze this file"


@pytest.mark.asyncio
@patch("app.excel_plugin.upload_bytes_to_dropzone")
@patch("app.excel_plugin.ingest_file")
async def test_plugin_on_user_message_callback(mock_ingest, mock_upload, sample_xlsx_bytes):
    mock_upload.return_value = "gs://dropzone/ajiteshk/test.xlsx"
    mock_ingest.return_value = {
        "status": "SUCCESS",
        "sheets": [
            {
                "sheet_name": "Sheet1",
                "table_name": "wb_ajiteshk_test_sheet1",
                "row_count": 1,
                "columns_schema": [],
                "sample_preview": [],
            }
        ],
    }

    plugin = ExcelSpreadsheetIngestionPlugin()
    inv_context = MagicMock()
    inv_context.user_id = "ajiteshk"

    user_msg = types.Content(
        role="user",
        parts=[
            types.Part.from_bytes(
                data=sample_xlsx_bytes,
                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        ],
    )

    result = await plugin.on_user_message_callback(
        invocation_context=inv_context,
        user_message=user_msg,
    )
    assert result is not None
    assert result.parts[0].inline_data is None
    assert "wb_ajiteshk_test_sheet1" in result.parts[0].text


@pytest.mark.asyncio
@patch("app.excel_plugin.upload_bytes_to_dropzone")
@patch("app.excel_plugin.ingest_file")
async def test_before_model_callback_hook(mock_ingest, mock_upload, sample_xlsx_bytes):
    mock_upload.return_value = "gs://dropzone/ajiteshk/hook.xlsx"
    mock_ingest.return_value = {
        "status": "SUCCESS",
        "sheets": [
            {
                "sheet_name": "Sheet1",
                "table_name": "wb_ajiteshk_hook_sheet1",
                "row_count": 1,
                "columns_schema": [],
                "sample_preview": [],
            }
        ],
    }

    cb_context = MagicMock()
    cb_context.user_id = "ajiteshk"

    p_bad = types.Part.from_bytes(
        data=sample_xlsx_bytes,
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    llm_req = MagicMock()
    llm_req.contents = [types.Content(role="user", parts=[p_bad])]

    await before_model_callback_hook(callback_context=cb_context, llm_request=llm_req)
    assert llm_req.contents[0].parts[0].inline_data is None
    assert "wb_ajiteshk_hook_sheet1" in llm_req.contents[0].parts[0].text
