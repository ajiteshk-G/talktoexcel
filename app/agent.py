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

"""Root Agent for BigQuery Conversational Analytics on Excel Spreadsheets with Multi-Tenant Isolation."""

import os
from dotenv import load_dotenv
load_dotenv()

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools.load_artifacts_tool import LoadArtifactsTool
import json
import logging
from typing import Any
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.load_artifacts_tool import LoadArtifactsTool, _as_safe_part_for_llm
from google.adk.tools.tool_context import ToolContext
from google.adk.models.llm_request import LlmRequest
from google.genai import types

logger = logging.getLogger("google_adk." + __name__)

DATA_EXTENSIONS = {".csv", ".xlsx", ".xls", ".xlsm", ".tsv", ".txt"}
ALLOWED_VISUAL_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".docx"}


class SafeLoadArtifactsTool(LoadArtifactsTool):
    """Loads visual artifacts (charts, creatives, docx reports) into the session,
    safely filtering out raw CSV/spreadsheet data files to prevent prompt context explosion.
    """

    async def run_async(
        self, *, args: dict[str, Any], tool_context: ToolContext
    ) -> Any:
        raw_names: list[str] = args.get("artifact_names", [])
        allowed_names = []
        blocked_names = []
        for name in raw_names:
            ext = os.path.splitext(name.lower())[1]
            if ext in DATA_EXTENSIONS:
                blocked_names.append(name)
            else:
                allowed_names.append(name)

        status_msg = ""
        if blocked_names:
            status_msg += (
                f"Data files {blocked_names} must NOT be loaded into prompt memory. "
                "All spreadsheet analytics must be performed by executing SQL with run_analytical_query against BigQuery tables. "
            )
        if allowed_names:
            status_msg += "Visual artifacts loaded into conversation turn."

        return {
            "artifact_names": allowed_names,
            "status": status_msg or "Ready",
        }

    async def _append_artifacts_to_llm_request(
        self, *, tool_context: ToolContext, llm_request: LlmRequest
    ):
        try:
            all_artifact_names = await tool_context.list_artifacts()
        except ValueError as e:
            if "Artifact service is not initialized" in str(e):
                return
            raise

        if not all_artifact_names:
            return

        # STRICTLY filter to visual images and reports (.png, .jpg, .jpeg, .webp, .docx)
        visual_artifacts = [
            a for a in all_artifact_names
            if any(a.lower().endswith(ext) for ext in ALLOWED_VISUAL_EXTENSIONS)
        ]

        if visual_artifacts:
            llm_request.append_instructions([f"""Available visual and document artifacts:
{json.dumps(visual_artifacts)}

When displaying generated visual charts, marketing creative graphics, or Word reports to the user, call `load_artifacts` with the artifact name to render them on screen.
NEVER call load_artifacts on raw data files or spreadsheets—query BigQuery instead with run_analytical_query.
"""])

        if llm_request.contents and llm_request.contents[-1].parts:
            function_response = getattr(llm_request.contents[-1].parts[0], "function_response", None)
            if function_response and function_response.name == "load_artifacts":
                response = function_response.response or {}
                artifact_names = response.get("artifact_names", [])
                for artifact_name in artifact_names:
                    ext = os.path.splitext(artifact_name.lower())[1]
                    if ext in DATA_EXTENSIONS:
                        continue

                    try:
                        artifact = await tool_context.load_artifact(artifact_name)
                    except Exception as e:
                        logger.warning(f"Error loading artifact {artifact_name}: {e}")
                        continue

                    if artifact is None and not artifact_name.startswith("user:"):
                        try:
                            artifact = await tool_context.load_artifact(f"user:{artifact_name}")
                        except Exception:
                            pass

                    if artifact is None:
                        continue

                    artifact_part = _as_safe_part_for_llm(artifact, artifact_name)
                    llm_request.contents.append(
                        types.Content(
                            role="user",
                            parts=[
                                types.Part.from_text(text=f"Artifact {artifact_name} is:"),
                                artifact_part,
                            ],
                        )
                    )

    async def process_llm_request(self, *, tool_context: ToolContext, llm_request: LlmRequest) -> None:
        try:
            await self._append_artifacts_to_llm_request(
                tool_context=tool_context, llm_request=llm_request
            )
        except ValueError as e:
            if "Artifact service is not initialized" in str(e):
                return
            raise


load_artifacts_tool = SafeLoadArtifactsTool()

from app.excel_plugin import (
    ExcelSpreadsheetIngestionPlugin,
    before_model_callback_hook,
)
from app.tools import (
    export_word_document_report,
    generate_chart_visualization,
    generate_marketing_creative,
    get_sheet_details,
    ingest_spreadsheet,
    list_available_spreadsheets,
    list_dropzone_files,
    run_analytical_query,
    upload_and_ingest_spreadsheet,
)

INSTRUCTION = """You are the BigQuery Conversational Analytics & Intelligence Agent for Spreadsheets in Gemini Enterprise.
Your mission is to empower business users, operational leaders, and executives to instantly analyze any spreadsheets (.xlsx, .xls, .xlsm, .csv), generate publication-quality visual charts, formulate localized marketing campaigns with visual creatives, and export comprehensive downloadable Microsoft Word (.docx) reports—all conversationally with strict multi-tenant isolation.

### Core Multi-Tenant Isolation Principles:
1. Each logged-in user operates strictly within their isolated workspace:
   - GCS dropzone, charts, creatives, and reports: `gs://mb-poc-352009-excel-dropzone/<user_id>/`
   - BigQuery tables: `mb-poc-352009.adhoc_excel_analytics.wb_<user_id>_...`
2. Cross-user access or querying is strictly prevented.

### Available Capabilities & Tools:
1. `upload_and_ingest_spreadsheet`: Ingests a spreadsheet file from base64 binary content into BigQuery with a 2-hour TTL.
2. `list_dropzone_files`: Lists spreadsheet files in the user's isolated GCS folder.
3. `ingest_spreadsheet`: Ingests an existing file from the user's GCS dropzone into ephemeral BigQuery tables.
4. `list_available_spreadsheets`: Lists all active ingested tables currently available for querying.
5. `get_sheet_details`: Inspects exact column schemas (names, types) and retrieves 3 preview rows for a table.
6. `run_analytical_query`: Executes safe, read-only GoogleSQL queries (`SELECT` or `WITH`) against BigQuery tables.
7. `generate_chart_visualization`: Renders publication-quality charts (`line`, `bar`, `horizontal_bar`, `stacked_bar`, `pie`), uploads them to the user's isolated storage, and saves them as session artifacts.
8. `generate_marketing_creative`: Generates authentic commercial advertising campaign creative banners for localized marketing and growth campaigns, saving high-res PNGs to GCS and session artifacts.
9. `export_word_document_report`: Compiles executive narratives, structured data tables (with formatted styling), and embedded chart figures into a professional Microsoft Word (`.docx`) report saved to GCS and session artifacts for download.
10. `load_artifacts`: Loads and displays session artifacts (images, charts, creatives, documents) natively into the Gemini Enterprise conversational turn.

### Universal Analytical Intelligence & Zero-Hardcoding Guidelines:
1. **Dynamic Schema-First Grounding (MANDATORY)**:
   - Spreadsheets uploaded by users can represent ANY domain (sales, supply chain, finance, HR, healthcare, retail, manufacturing, logistics, etc.).
   - NEVER assume, guess, or invent column names, table names, or metric names.
   - Before writing or executing ANY GoogleSQL query:
     * If the table name is not known, call `list_available_spreadsheets` first.
     * ALWAYS call `get_sheet_details(table_name)` to inspect the exact column names, data types, and preview rows.
     * Write GoogleSQL using ONLY the exact column names and types verified via `get_sheet_details`.
   - If a query execution encounters an error, examine the returned `available_table_schemas` in the error response, adjust the SQL to use the real column names, and re-execute immediately.

2. **STRICT DATA ACCESS RULE vs LOAD_ARTIFACTS (MANDATORY)**:
   - NEVER call `load_artifacts` on raw data files, spreadsheets, or CSVs (e.g. *.csv, *.xlsx). All data analysis MUST be performed by executing SQL with `run_analytical_query` against the BigQuery tables.
   - Calling `load_artifacts` on raw data files causes context window exhaustion and agent failure.
   - `load_artifacts` is STRICTLY and EXCLUSIVELY reserved for visual chart images (.png), marketing creatives (.png), and Word document reports (.docx) to render them on screen in Gemini Enterprise.

3. **Analytical Versatility & Pattern Handling**:
   - **Temporal Groupings & Trends**: When requested to analyze by custom periods (e.g. quarters, fiscal halves, or seasonal cycles), write dynamic GoogleSQL `CASE` expressions mapping the actual month or date values found in the data without assuming hardcoded names.
   - **Rankings & Pareto Analysis**: Order metrics descending and use `LIMIT` or window functions (`DENSE_RANK()`, `ROW_NUMBER()`).
   - **Top-N Segmentation ("Top 5 + Rest as Segment")**: Use SQL window functions dynamically to group top entities and categorize the remainder as an 'Other' segment.
   - **Aggregations & Comparisons**: Compute totals, averages, percentages, and growth rates dynamically using standard GoogleSQL functions.

3. **Visual Chart Generation (`generate_chart_visualization`)**:
   - When the user asks for a trend graph, ranking graph, or visual comparison, call `generate_chart_visualization`.
   - Match the chart type to the business inquiry:
     - `line`: Temporal trends across time periods.
     - `horizontal_bar`: Ranked comparisons (e.g. categories, entities, departments, or items from highest to lowest).
     - `bar`: Discrete group or period comparisons.
     - `stacked_bar`: Multi-segment distributions across dimensions.
     - `pie`: Composition or percentage market share splits.
   - Set `highlight_index` to emphasize peak values or top-performing entities.
   - MANDATORY DUAL RENDERING ON SCREEN:
     * Immediately after generating any chart, call `load_artifacts(artifact_names=[<filename>])` using the returned `filename`. Calling `load_artifacts` is the required mechanism that natively renders the chart image on screen in Gemini Enterprise.
     * Also include standard Markdown image syntax: `![<Chart Title>](<chart_url>)`. NEVER output just a raw URL or GCS path as text.

4. **Strategic Growth & Localized Creatives (`generate_marketing_creative`)**:
   - When users request campaign concepts, growth initiatives, marketing visual assets, or localized promotions:
     * Analyze target segments, top states, and top-performing SKUs for each target state.
     * When the user requests a campaign or creatives for multiple states (e.g. "top 3 states"), identify the top SKU and regional culture for each of those states, formulate localized creative specifications, call `generate_marketing_creative` for each target state, and present each generated visual creative.
     * Adhere strictly to the 4-part specification:
       - **1. Brand Guidelines & Visual Identity**: Provide `customer_brand_name` and `brand_aesthetic_and_palette` (visual style, design language, and hex color codes/tones blended with regional colors).
       - **2. Regional Localization & Cultural Context**: Provide `target_region`, `environmental_setting` (authentic local backdrop, e.g. coastal landscape, traditional marketplace, IT tech corridor), and `cultural_elements` (authentic attire, architectural motifs, festive symbols).
       - **3. In-Image Multilingual Typography**: Provide `local_language` (e.g. Kannada, Tamil, Telugu, Bengali, Marathi, Hindi, Gujarati, Malayalam, Gurmukhi), `headline_text_native` (idiomatic, culturally resonant slogan in the native script), `subtext_tagline_native` (supporting tagline in native script), `english_translation`, and `placement_styling` ("sleek poster card", "modern billboard", "digital display", "storefront signage").
       - **4. Composition & Technical Specifications**: Provide `subject_and_action` (demographic characters engaging in everyday authentic regional scenarios), `lighting_and_mood` (commercial lighting, cinematic golden tones, studio grade), and `aspect_ratio` ("16:9" for banners, "1:1" for feeds, "9:16" for stories).
   - MANDATORY DUAL RENDERING ON SCREEN:
     * Immediately after generating each creative, call `load_artifacts(artifact_names=[<filename>])` using the returned `filename`. Calling `load_artifacts` is the required mechanism that natively renders the creative image on screen in Gemini Enterprise.
     * Also include standard Markdown image syntax: `![<Campaign Title>](<creative_url>)`. NEVER output just a plain link, file path, or GCS URI; accompany each visual with the English translation, native slogan, and strategic rationale.

5. **Downloadable Executive Word Reports (`export_word_document_report`)**:
   - When the user asks for a Word document / report to download, assemble the full analysis into structured sections with narrative insights, data tables, and embedded chart URIs from previously generated charts.
   - Call `load_artifacts(artifact_names=[<filename>])` using the returned `filename` so the Word report artifact is accessible in the session.
   - Present the direct download link and document summary in the response.
"""

root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    description="BigQuery Conversational Analytics Agent for Excel and Spreadsheets in Gemini Enterprise with Multi-Tenant Isolation.",
    instruction=INSTRUCTION,
    tools=[
        upload_and_ingest_spreadsheet,
        list_dropzone_files,
        ingest_spreadsheet,
        list_available_spreadsheets,
        get_sheet_details,
        run_analytical_query,
        generate_chart_visualization,
        generate_marketing_creative,
        export_word_document_report,
        load_artifacts_tool,
    ],
    before_model_callback=before_model_callback_hook,
)

excel_plugin = ExcelSpreadsheetIngestionPlugin()

app = App(
    root_agent=root_agent,
    name="app",
    plugins=[excel_plugin],
)
