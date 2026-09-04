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

"""Unit tests for A2UI surface payload builders and catalog invariants."""

import json
import pytest
from app.a2ui.builder import (
    build_v09_canvas_surface,
    build_webframe_surface,
    create_a2ui_inline_part,
    wrap_messages_as_a2a_parts,
)
from app.a2ui.catalog import (
    A2UI_MIME_TYPE,
    A2UI_V08_GE_CUSTOM_CATALOG_URI,
    A2UI_V08_STANDARD_CATALOG_URI,
    A2UI_V09_COMPOSITE_CATALOG_URI,
    COMPONENT_CANVAS,
    COMPONENT_COLUMN,
    COMPONENT_IFRAME_SRCDOC,
    COMPONENT_WEB_FRAME_SRCDOC,
)


def test_build_webframe_surface_structure():
    """Verify build_webframe_surface satisfies all Gemini Enterprise A2UI invariants."""
    html_content = "<html><body><h1>Hello A2UI</h1></body></html>"
    surface_id = "test_surface_123"

    messages = build_webframe_surface(
        html_content=html_content,
        surface_id=surface_id,
        height=620,
        title="Vendor Spend Overview",
        subtitle="Ad-hoc Financial Drilldown",
    )

    assert len(messages) == 2

    # 1. Inspect beginRendering
    begin_rendering = messages[0].get("beginRendering")
    assert begin_rendering is not None
    assert begin_rendering["surfaceId"] == surface_id
    assert begin_rendering["catalogId"] == A2UI_V08_GE_CUSTOM_CATALOG_URI
    root_id = begin_rendering["root"]
    assert root_id == "iframe_root"

    # 2. Inspect surfaceUpdate
    surface_update = messages[1].get("surfaceUpdate")
    assert surface_update is not None
    assert surface_update["surfaceId"] == surface_id
    components = surface_update["components"]
    assert len(components) == 1

    # Invariant: root component ID matches byte-for-byte
    root_comp = components[0]
    assert root_comp["id"] == root_id
    assert COMPONENT_WEB_FRAME_SRCDOC in root_comp["component"]
    wf_props = root_comp["component"][COMPONENT_WEB_FRAME_SRCDOC]
    assert wf_props["htmlContent"]["literalString"] == html_content
    assert wf_props["height"] == 620
    assert wf_props["cardTitle"] == "Vendor Spend Overview"
    assert wf_props["cardDescription"] == "Ad-hoc Financial Drilldown"
    assert wf_props["cardIcon"] == "analytics"
    assert wf_props["autoOpen"] is True


def test_create_a2ui_inline_part():
    """Verify create_a2ui_inline_part packages messages into Discovery Engine Assistant Service envelope."""
    msg = {"beginRendering": {"surfaceId": "s1", "root": "r1"}}
    part = create_a2ui_inline_part(msg)

    assert part.inline_data is not None
    assert part.inline_data.mime_type == "text/plain"
    raw_text = part.inline_data.data.decode("utf-8")
    assert raw_text.startswith("<a2a_datapart_json>")
    assert raw_text.endswith("</a2a_datapart_json>")
    inner = json.loads(raw_text[len("<a2a_datapart_json>"):-len("</a2a_datapart_json>")])
    assert inner["metadata"]["mimeType"] == A2UI_MIME_TYPE
    assert inner["data"] == msg


def test_build_webframe_surface_empty_error():
    """Verify build_webframe_surface rejects empty html content."""
    with pytest.raises(ValueError, match="html_content cannot be empty"):
        build_webframe_surface(html_content="")

    with pytest.raises(ValueError, match="html_content cannot be empty"):
        build_webframe_surface(html_content="   \n  ")


def test_build_webframe_surface_auto_surface_id():
    """Verify build_webframe_surface automatically generates unique surfaceId if omitted."""
    html = "<p>Data</p>"
    m1 = build_webframe_surface(html)
    m2 = build_webframe_surface(html)

    s1 = m1[0]["beginRendering"]["surfaceId"]
    s2 = m2[0]["beginRendering"]["surfaceId"]
    assert s1.startswith("surface_")
    assert s2.startswith("surface_")
    assert s1 != s2


def test_build_v09_canvas_surface():
    """Verify v0.9 Canvas side-panel surface builder produces expected composite structure."""
    html = "<div>Side Panel</div>"
    messages = build_v09_canvas_surface(
        html_content=html,
        surface_id="canvas_123",
        height=750,
        title="Sales Explorer",
    )
    assert len(messages) == 2
    br = messages[0]["beginRendering"]
    assert br["surfaceId"] == "canvas_123"
    assert br["catalogId"] == A2UI_V09_COMPOSITE_CATALOG_URI
    assert br["root"] == "canvas_root"

    su = messages[1]["surfaceUpdate"]
    assert su["surfaceId"] == "canvas_123"
    canvas_comp = su["components"][0]
    assert canvas_comp["id"] == "canvas_root"
    assert COMPONENT_CANVAS in canvas_comp["component"]
    assert canvas_comp["component"][COMPONENT_CANVAS]["isSidePanelSurface"] is True
    assert canvas_comp["component"][COMPONENT_CANVAS]["title"]["literalString"] == "Sales Explorer"

    iframe_comp = su["components"][1]
    assert COMPONENT_IFRAME_SRCDOC in iframe_comp["component"]
    assert iframe_comp["component"][COMPONENT_IFRAME_SRCDOC]["height"] == 750


def test_wrap_messages_as_a2a_parts():
    """Verify wrapping A2UI messages into A2A DataPart envelopes with official MIME type."""
    html = "<b>Visual</b>"
    messages = build_webframe_surface(html, surface_id="s_test")
    parts = wrap_messages_as_a2a_parts(messages)

    assert len(parts) == 2
    for p in parts:
        assert p["kind"] == "data"
        assert p["metadata"]["mimeType"] == A2UI_MIME_TYPE
        assert "data" in p
