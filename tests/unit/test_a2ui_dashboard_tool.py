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

"""Unit tests for the A2UI interactive dashboard tool and HTML template generator."""

from unittest.mock import AsyncMock, MagicMock
import pytest
from app.a2ui.templates.dashboard import generate_dashboard_html
from app.tools import render_interactive_dashboard


def test_generate_dashboard_html_bar_chart():
    """Verify HTML generation for a bar chart dashboard."""
    html_out = generate_dashboard_html(
        title="Q3 Sales Dashboard",
        summary_metrics=[
            {"label": "Total Revenue", "value": "$1,250,000", "delta": "+12.4%", "is_positive": True},
            {"label": "Returns", "value": "$4,200", "delta": "-2.1%", "is_positive": False},
        ],
        chart_type="bar",
        chart_data={
            "labels": ["July", "August", "September"],
            "datasets": [{"label": "Revenue ($)", "data": [380000, 420000, 450000]}],
        },
        table_headers=["Month", "Orders", "Revenue"],
        table_rows=[
            ["July", 1200, 380000],
            ["August", 1450, 420000],
            ["September", 1580, 450000],
        ],
        suggested_actions=[
            {"label": "Export Word Report", "name": "export_word_report", "context": {"quarter": "Q3"}},
            {"label": "Generate Creative", "name": "generate_creative", "context": {}},
        ],
        subtitle="Regional Performance Breakdown",
    )

    # 1. Structural assertions
    assert "<!DOCTYPE html>" in html_out
    assert "Q3 Sales Dashboard" in html_out
    assert "Regional Performance Breakdown" in html_out
    assert "Total Revenue" in html_out
    assert "$1,250,000" in html_out
    assert "Export Word Report" in html_out

    # 2. CSP compliance assertion: strictly NO external script or stylesheet links
    assert "http://" not in html_out.lower() or "schemas" in html_out
    assert "https://" not in html_out or "schemas" in html_out
    assert "<script src=" not in html_out
    assert "<link rel=\"stylesheet\" href=" not in html_out

    # 3. Bidirectional postMessage integration assertion
    assert "window.parent.postMessage" in html_out
    assert "a2ui_action" in html_out


def test_generate_dashboard_html_donut_chart():
    """Verify HTML generation for a donut chart distribution."""
    html_out = generate_dashboard_html(
        title="Market Share by Region",
        chart_type="donut",
        chart_data={
            "labels": ["North", "South", "East", "West"],
            "values": [35, 25, 20, 20],
        },
    )
    assert "Market Share by Region" in html_out
    assert "renderDonutChart" in html_out
    assert "svgChart" in html_out


def test_generate_dashboard_html_line_chart():
    """Verify HTML generation for a line trend chart."""
    html_out = generate_dashboard_html(
        title="Monthly Trend Analysis",
        chart_type="line",
        chart_data={
            "labels": ["Jan", "Feb", "Mar", "Apr"],
            "datasets": [{"label": "Active Users", "data": [1000, 1400, 1900, 2400]}],
        },
    )
    assert "Monthly Trend Analysis" in html_out
    assert "renderLineChart" in html_out


@pytest.mark.asyncio
async def test_render_interactive_dashboard_tool_execution():
    """Verify async execution of render_interactive_dashboard tool."""
    mock_context = MagicMock()
    mock_context.user_id = "user_analyst_01"
    mock_context.session = MagicMock()
    mock_context.session.user_id = "user_analyst_01"
    mock_context.save_artifact = AsyncMock()

    result = await render_interactive_dashboard(
        title="Executive Performance Summary",
        summary_metrics=[
            {"label": "ARR", "value": "$10.5M", "delta": "+28%", "is_positive": True},
        ],
        chart_type="horizontal_bar",
        chart_data={
            "labels": ["Enterprise", "Mid-Market", "SMB"],
            "datasets": [{"label": "ARR ($M)", "data": [6.2, 2.8, 1.5]}],
        },
        table_headers=["Segment", "ARR ($M)", "Customers"],
        table_rows=[
            ["Enterprise", 6.2, 45],
            ["Mid-Market", 2.8, 180],
            ["SMB", 1.5, 950],
        ],
        suggested_actions=[
            {"label": "Download Docx", "name": "export_word_report"},
        ],
        tool_context=mock_context,
    )

    assert result["status"] == "SUCCESS"
    assert result["title"] == "Executive Performance Summary"
    assert result["chart_type"] == "horizontal_bar"
    assert result["user_id"] == "user_analyst_01"

    # Verify A2UI payload structure
    a2ui_payload = result["a2ui_payload"]
    assert len(a2ui_payload) == 2
    assert "beginRendering" in a2ui_payload[0]
    assert "surfaceUpdate" in a2ui_payload[1]
    assert result["surface_id"] == a2ui_payload[0]["beginRendering"]["surfaceId"]

    # Verify save_artifact was called for session persistence
    assert mock_context.save_artifact.called
    saved_filename = mock_context.save_artifact.call_args[1]["filename"]
    assert saved_filename.startswith("dashboard_")
    assert saved_filename.endswith(".html")
