# Copyright 2026 Google LLC

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.tools import (
    export_word_document_report,
    generate_chart_visualization,
    generate_marketing_creative,
    validate_sql,
)


@pytest.fixture
def mock_storage_upload():
    with patch("app.tools.upload_user_artifact_to_gcs") as mock_upload:
        mock_upload.side_effect = lambda user_id, subfolder, filename, data_bytes, content_type: (
            f"gs://mb-poc-352009-excel-dropzone/{user_id}/{subfolder}/{filename}",
            f"https://storage.googleapis.com/mb-poc-352009-excel-dropzone/{user_id}/{subfolder}/{filename}",
        )
        yield mock_upload


@pytest.fixture(autouse=True)
def mock_gemini_image_gen():
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_candidate = MagicMock()
    mock_part = MagicMock()
    mock_part.inline_data = MagicMock()
    mock_part.inline_data.data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    mock_candidate.content.parts = [mock_part]
    mock_resp.candidates = [mock_candidate]
    mock_client.models.generate_content.return_value = mock_resp

    with patch("app.tools.genai.Client", return_value=mock_client) as patcher:
        yield patcher


@pytest.mark.asyncio
async def test_generate_chart_visualization_line(mock_storage_upload):
    labels = ["Aug 2025", "Sep 2025", "Oct 2025", "Nov 2025", "Dec 2025", "Apr 2026", "May 2026"]
    datasets = [{"label": "Sales Value (₹ Cr)", "data": [12.4, 14.2, 16.8, 15.1, 13.9, 17.5, 18.2]}]
    res = await generate_chart_visualization(
        chart_type="line",
        title="Month-by-Month Biscuits Sales Value Trend",
        labels=labels,
        datasets=datasets,
        x_label="Month",
        y_label="Sales Value",
        highlight_index=6,
        currency_or_unit="₹ Cr",
    )
    assert res["status"] == "SUCCESS"
    assert "Month-by-Month" in res["title"]
    assert res["chart_url"].startswith("https://storage.googleapis.com/")
    assert res["markdown_image"].startswith("![")
    assert "filename" in res
    assert mock_storage_upload.called


@pytest.mark.asyncio
async def test_generate_chart_visualization_horizontal_bar(mock_storage_upload):
    labels = ["MAHARASHTRA", "UTTAR PRADESH", "WEST BENGAL", "TAMIL NADU", "BIHAR"]
    datasets = [{"label": "Sales Value (₹ Cr)", "data": [45.2, 38.9, 34.1, 29.5, 22.0]}]
    res = await generate_chart_visualization(
        chart_type="horizontal_bar",
        title="Sales Value by State (Highest to Lowest)",
        labels=labels,
        datasets=datasets,
        x_label="State",
        y_label="Sales Value",
        highlight_index=0,
        currency_or_unit="₹ Cr",
    )
    assert res["status"] == "SUCCESS"
    assert res["chart_type"] == "horizontal_bar"
    assert res["user_id"] == "default_user"


@pytest.mark.asyncio
async def test_generate_chart_visualization_stacked_bar(mock_storage_upload):
    labels = ["Monsoon 2025-2026", "Winter 2025-2026", "Summer 2026-2027"]
    datasets = [
        {"label": "SF Dark Fantasy", "data": [10.2, 8.5, 14.1]},
        {"label": "SF Mom's Magic", "data": [9.1, 7.8, 12.3]},
        {"label": "Other SKUs", "data": [25.4, 20.1, 31.0]},
    ]
    res = await generate_chart_visualization(
        chart_type="stacked_bar",
        title="Seasonal Sales Volume: Top SKUs vs Other Segment",
        labels=labels,
        datasets=datasets,
        x_label="Indian Season",
        y_label="Sales Volume (MT)",
    )
    assert res["status"] == "SUCCESS"
    assert res["chart_type"] == "stacked_bar"


@pytest.mark.asyncio
async def test_generate_chart_visualization_saves_artifact(mock_storage_upload):
    mock_ctx = MagicMock()
    mock_ctx.user_id = "test_user_gaia"
    mock_ctx.save_artifact = AsyncMock(return_value=0)

    res = await generate_chart_visualization(
        chart_type="bar",
        title="State Sales Comparison",
        labels=["State A", "State B"],
        datasets=[{"label": "Sales", "data": [10.0, 20.0]}],
        tool_context=mock_ctx,
    )
    assert res["status"] == "SUCCESS"
    assert "filename" in res
    assert mock_ctx.save_artifact.called
    call_args = mock_ctx.save_artifact.call_args
    assert call_args.kwargs["filename"] == res["filename"]
    assert call_args.kwargs["artifact"].inline_data.mime_type == "image/png"


@pytest.mark.asyncio
async def test_generate_marketing_creative_bengali(mock_storage_upload):
    res = await generate_marketing_creative(
        campaign_title="Sunfeast Mom's Magic - Bengal Cha Special",
        brand_and_sku="Sunfeast Mom's Magic Butter & Cashew",
        target_state="West Bengal",
        regional_language="Bengali",
        headline_text="প্রতিটি চায়ে সানফিস্টের মিষ্টি ছোঁয়া",
        subheadline_text="Rich Butter & Roasted Cashew - Best Companion for Bengal Cha",
        campaign_theme="Morning Chai Ritual",
    )
    assert res["status"] == "SUCCESS"
    assert res["target_state"] == "West Bengal"
    assert res["regional_language"] == "Bengali"
    assert res["creative_url"].endswith(".png")
    assert "![Sunfeast Mom's Magic" in res["markdown_image"]
    assert "filename" in res


@pytest.mark.asyncio
async def test_generate_marketing_creative_tamil(mock_storage_upload):
    res = await generate_marketing_creative(
        campaign_title="Sunfeast Dark Fantasy - Tamil Nadu Indulgence",
        brand_and_sku="Sunfeast Dark Fantasy Choco Fills",
        target_state="Tamil Nadu",
        regional_language="Tamil",
        headline_text="சுவைமிக்க சாக்லேட் ஆனந்தம்",
        subheadline_text="Pure Molten Chocolate Indulgence in Every Bite",
        campaign_theme="Premium Festive Indulgence",
    )
    assert res["status"] == "SUCCESS"
    assert res["target_state"] == "Tamil Nadu"
    assert res["regional_language"] == "Tamil"


@pytest.mark.asyncio
async def test_generate_marketing_creative_comprehensive_spec_kannada_1_to_1(mock_storage_upload):
    res = await generate_marketing_creative(
        customer_brand_name="Sunfeast Dark Fantasy",
        target_region="Karnataka",
        local_language="Kannada",
        headline_text_native="ಅಪ್ಪಟ ಚಾಕೊಲೇಟ್ ಆನಂದ",
        subtext_tagline_native="ಪ್ರತಿಯೊಂದು ತುತ್ತಿನಲ್ಲೂ ಕರಗುವ ಚಾಕೊಲೇಟ್",
        english_translation="Pure chocolate bliss in every bite",
        brand_aesthetic_and_palette="Opulent dark chocolate tones with gold accents #f4b400",
        environmental_setting="Bangalore IT corridor coffee break and historic Mysore heritage backdrop",
        cultural_elements="Contemporary urban lifestyle blended with Mysore silk motifs",
        placement_styling="sleek poster card",
        subject_and_action="Young professionals sharing dark chocolate biscuits during an evening café break",
        lighting_and_mood="Warm cinematic golden hour lighting with soft bokeh",
        aspect_ratio="1:1",
        key_selling_points=["Molten chocolate center", "Crisp cookie shell", "Premium indulgence"],
    )
    assert res["status"] == "SUCCESS"
    assert res["customer_brand_name"] == "Sunfeast Dark Fantasy"
    assert res["target_region"] == "Karnataka"
    assert res["local_language"] == "Kannada"
    assert res["aspect_ratio"] == "1:1"
    assert "image_prompt_specification" in res
    spec = res["image_prompt_specification"]
    assert "### 1. Brand Guidelines & Visual Identity:" in spec
    assert "### 2. Regional Localization & Cultural Context:" in spec
    assert "### 3. In-Image Multilingual Typography:" in spec
    assert "### 4. Composition & Technical Specifications:" in spec
    assert "Kannada" in spec
    assert "ಅಪ್ಪಟ ಚಾಕೊಲೇಟ್ ಆನಂದ" in spec


@pytest.mark.asyncio
async def test_generate_marketing_creative_saves_artifact(mock_storage_upload):
    mock_ctx = MagicMock()
    mock_ctx.user_id = "test_user_gaia"
    mock_ctx.save_artifact = AsyncMock(return_value=0)

    res = await generate_marketing_creative(
        customer_brand_name="Sunfeast Bounce",
        target_region="Maharashtra",
        local_language="Marathi",
        headline_text_native="चविष्ट क्रीम बिस्किटे",
        tool_context=mock_ctx,
    )
    assert res["status"] == "SUCCESS"
    assert "filename" in res
    assert mock_ctx.save_artifact.called
    call_args = mock_ctx.save_artifact.call_args
    assert call_args.kwargs["filename"] == res["filename"]
    assert call_args.kwargs["artifact"].inline_data.mime_type == "image/png"


@pytest.mark.asyncio
async def test_generate_marketing_creative_telugu_9_to_16(mock_storage_upload):
    res = await generate_marketing_creative(
        customer_brand_name="Sunfeast Mom's Magic",
        target_region="Andhra Pradesh & Telangana",
        local_language="Telugu",
        headline_text_native="అమ్మ ప్రేమ వంటి మధురమైన రుచి",
        subtext_tagline_native="వెన్న మరియు జీడిపప్పుల అద్భుత కలయిక",
        english_translation="Sweet taste just like mother's love",
        brand_aesthetic_and_palette="Warm butter gold and roasted cashew cream #e67c73",
        environmental_setting="Traditional South Indian breakfast setting with filter coffee",
        cultural_elements="Traditional brass filter coffee dabarah and festive muggu kolam patterns",
        placement_styling="digital display",
        subject_and_action="Mother serving hot tea and biscuits to family on a Sunday morning",
        lighting_and_mood="Bright morning sunlight streaming through open courtyard",
        aspect_ratio="9:16",
    )
    assert res["status"] == "SUCCESS"
    assert res["target_region"] == "Andhra Pradesh & Telangana"
    assert res["local_language"] == "Telugu"
    assert res["aspect_ratio"] == "9:16"
    assert "Telugu" in res["image_prompt_specification"]


@pytest.mark.asyncio
async def test_export_word_document_report(mock_storage_upload):
    sections = [
        {
            "heading": "Month-by-Month Sales Trend",
            "narrative": "Sales value demonstrated consistent month-over-month acceleration, peaking in May 2026.",
            "table": {
                "headers": ["Month", "Year", "Sales Value (₹)", "MoM Variance %"],
                "rows": [
                    ["August", "2025-2026", "12,450,000", "--"],
                    ["September", "2025-2026", "14,200,000", "+14.0%"],
                    ["May", "2026-2027", "18,200,000", "+28.1%"],
                ],
            },
        },
        {
            "heading": "Regional Distribution",
            "narrative": "East District (EDIS) and South District (SDIS) accounted for 65% of overall biscuits sales.",
            "table": {
                "headers": ["Region Code", "Region Name", "Sales Share %"],
                "rows": [
                    ["EDIS", "East Region", "38.2%"],
                    ["SDIS", "South Region", "26.8%"],
                    ["WDIS", "West Region", "19.5%"],
                    ["NDIS", "North Region", "15.5%"],
                ],
            },
        },
    ]

    mock_ctx = MagicMock()
    mock_ctx.user_id = "test_user_gaia"
    mock_ctx.save_artifact = AsyncMock(return_value=0)

    res = await export_word_document_report(
        report_title="All-India Biscuits Sales Trend Analysis Report",
        executive_summary="This comprehensive report synthesizes sales performance across 34 states, 4 regions, and key Indian seasons.",
        sections=sections,
        tool_context=mock_ctx,
    )
    assert res["status"] == "SUCCESS"
    assert res["filename"].endswith(".docx")
    assert res["file_size_kb"] > 0
    assert res["download_url"].startswith("https://storage.googleapis.com/")
    assert mock_ctx.save_artifact.called
    call_args = mock_ctx.save_artifact.call_args
    assert call_args.kwargs["filename"] == res["filename"]
    assert call_args.kwargs["artifact"].inline_data.mime_type.endswith("wordprocessingml.document")


@pytest.mark.asyncio
async def test_export_word_document_report_with_markdown_table_and_model(mock_storage_upload):
    from app.tools import ReportSection

    sections = [
        ReportSection(
            heading="Quarterly Momentum",
            narrative="Sales expanded across all quarters, led by seasonal peaks.",
            table_markdown="""| Quarter | Sales ($M) | Growth % |
|:---|:---|:---|
| Q1 | $10.5 | Baseline |
| Q2 | $12.8 | +21.9% |
| Q3 | $14.2 | +10.9% |
| Q4 | $13.5 | -4.9% |""",
            chart_uris=["gs://mb-poc-352009-excel-dropzone/default_user/charts/sample_chart.png"],
        ),
        ReportSection(
            heading="Strategic Recommendations",
            narrative="Focus promotional budget on mid-year seasonal stabilization and expanding top-performing lines.",
        ),
    ]

    mock_ctx = MagicMock()
    mock_ctx.user_id = "test_user_pydantic"
    mock_ctx.save_artifact = AsyncMock(return_value=0)

    res = await export_word_document_report(
        report_title="Quarterly Sales Trend Analysis",
        executive_summary="Fiscal year performance exceeded internal targets with strong momentum across key quarters.",
        sections=sections,
        tool_context=mock_ctx,
    )
    assert res["status"] == "SUCCESS"
    assert res["filename"].endswith(".docx")
    assert res["file_size_kb"] > 0
    assert "download_url" in res
    assert mock_ctx.save_artifact.called


def test_domain_seasonality_sql_validation():
    user = "test_user"
    season_query = f"""
        SELECT
            CASE
                WHEN month IN ('March', 'April', 'May') THEN 'Summer'
                WHEN month IN ('June', 'July', 'August', 'September') THEN 'Monsoon'
                WHEN month IN ('October', 'November') THEN 'Post-Monsoon'
                WHEN month IN ('December', 'January', 'February') THEN 'Winter'
                ELSE 'Other'
            END AS season,
            year,
            SUM(sales_value) AS total_sales_volume
        FROM `mb-poc-352009.adhoc_excel_analytics.wb_{user}_biscuits`
        GROUP BY 1, 2
        ORDER BY total_sales_volume DESC
    """
    is_valid, err = validate_sql(season_query, user_slug=user)
    assert is_valid, f"Season query should be valid, got: {err}"

    sku_segment_query = f"""
        WITH ranked_skus AS (
            SELECT
                market_sku_description,
                SUM(sales_value) as sku_sales,
                DENSE_RANK() OVER (ORDER BY SUM(sales_value) DESC) as rnk
            FROM `mb-poc-352009.adhoc_excel_analytics.wb_{user}_biscuits`
            GROUP BY 1
        )
        SELECT
            CASE WHEN rnk <= 5 THEN market_sku_description ELSE 'Other SKUs' END AS sku_segment,
            SUM(sku_sales) AS segment_sales
        FROM ranked_skus
        GROUP BY 1
        ORDER BY segment_sales DESC
    """
    is_valid, err = validate_sql(sku_segment_query, user_slug=user)
    assert is_valid, f"SKU segment query should be valid, got: {err}"


def test_run_analytical_query_dynamic_schema_feedback():
    from app.tools import run_analytical_query
    from unittest.mock import MagicMock, patch

    user = "testuser"
    sql = "SELECT state_name, SUM(sales_value) FROM `mb-poc-352009.adhoc_excel_analytics.wb_testuser_sales` GROUP BY 1"

    mock_client = MagicMock()
    mock_client.query.side_effect = Exception("400 Unrecognized name: state_name at [1:8]")

    mock_table = MagicMock()
    f1 = MagicMock()
    f1.name = "state"
    f1.field_type = "STRING"
    f2 = MagicMock()
    f2.name = "sales_value"
    f2.field_type = "FLOAT64"
    mock_table.schema = [f1, f2]
    mock_client.get_table.return_value = mock_table

    mock_ctx = MagicMock()
    mock_ctx.user_id = user

    with patch("google.cloud.bigquery.Client", return_value=mock_client):
        res = run_analytical_query(sql, tool_context=mock_ctx)

    assert res["status"] == "ERROR"
    assert "Unrecognized name: state_name" in res["error"]
    assert "available_table_schemas" in res
    assert "wb_testuser_sales" in res["available_table_schemas"]
    assert res["available_table_schemas"]["wb_testuser_sales"] == [
        {"name": "state", "type": "STRING"},
        {"name": "sales_value", "type": "FLOAT64"},
    ]
    assert "hint" in res


@pytest.mark.asyncio
async def test_safe_load_artifacts_tool_registration_and_dispatch():
    from app.agent import root_agent, SafeLoadArtifactsTool
    from google.adk.flows.llm_flows.base_llm_flow import _process_agent_tools, LlmRequest
    from google.genai import types

    # 1. Verify load_artifacts tool is present in tools_dict after process_agent_tools
    req = LlmRequest(model="gemini-flash-latest", config=types.GenerateContentConfig())
    mock_inv_ctx = MagicMock()
    mock_inv_ctx.agent = root_agent
    mock_inv_ctx.session.state = {}
    mock_inv_ctx.artifact_service = None

    await _process_agent_tools(mock_inv_ctx, req)
    assert "load_artifacts" in req.tools_dict, "load_artifacts must be registered in tools_dict"
    assert any(
        fd.name == "load_artifacts"
        for t in req.config.tools
        for fd in getattr(t, "function_declarations", [])
    ), "load_artifacts function declaration must be present in config.tools"

    # 2. Verify SafeLoadArtifactsTool run_async filtering
    tool = SafeLoadArtifactsTool()
    tool_ctx = MagicMock()

    # Filters out raw data files and keeps visual files
    res = await tool.run_async(
        args={"artifact_names": ["raw_sales.csv", "chart.png", "data.xlsx"]},
        tool_context=tool_ctx,
    )
    assert res["artifact_names"] == ["chart.png"]
    assert "must NOT be loaded into prompt memory" in res["status"]

    # Also supports single artifact_name
    res_single = await tool.run_async(
        args={"artifact_name": "marketing_banner.png"},
        tool_context=tool_ctx,
    )
    assert res_single["artifact_names"] == ["marketing_banner.png"]


def test_serialize_event_for_json_with_artifacts():
    import json
    import base64
    from google.genai import types
    from vertexai.agent_engines.templates.adk import _Artifact, _ArtifactVersion, _StreamingRunResponse
    from app.app_utils.reasoning_engine_adapter import serialize_event_for_json

    part = types.Part.from_bytes(data=b"\x89PNG\r\n\x1a\nFakePngData", mime_type="image/png")
    version = _ArtifactVersion(version=0, data=part)
    artifact = _Artifact(file_name="sales_chart_2026.png", versions=[version])
    response = _StreamingRunResponse(events=[], artifacts=[artifact], session_id="test_sess_123")
    dumped = response.dump()

    # Verify serialize_event_for_json serializes without TypeError: Object of type Part is not JSON serializable
    json_str = serialize_event_for_json(dumped)
    assert isinstance(json_str, str)

    parsed = json.loads(json_str)
    assert parsed["session_id"] == "test_sess_123"
    assert len(parsed["artifacts"]) == 1
    art = parsed["artifacts"][0]
    assert art["file_name"] == "sales_chart_2026.png"
    v0_data = art["versions"][0]["data"]
    assert v0_data["inline_data"]["mime_type"] == "image/png"
    assert base64.b64decode(v0_data["inline_data"]["data"]) == b"\x89PNG\r\n\x1a\nFakePngData"



