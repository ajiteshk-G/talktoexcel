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

"""Payload builders for A2UI WebFrame and Canvas surfaces in Gemini Enterprise."""

import json
import uuid
from typing import Any, Dict, List, Optional

from google.genai import types

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


def build_webframe_surface(
    html_content: str,
    surface_id: Optional[str] = None,
    height: int = 650,
    title: Optional[str] = None,
    subtitle: Optional[str] = None,
    root_id: str = "iframe_root",
    catalog_id: str = A2UI_V08_GE_CUSTOM_CATALOG_URI,
) -> List[Dict[str, Any]]:
    """Builds the canonical A2UI v0.8 message sequence (beginRendering + surfaceUpdate)
    for rendering an isolated, sandboxed WebFrameSrcdoc in Gemini Enterprise.

    Critical A2UI Invariants Enforced:
    1. The root component ID declared in `beginRendering.root` MUST be byte-identical
       to the ID of the root component in `surfaceUpdate.components`.
    2. The `surfaceId` in `beginRendering` and `surfaceUpdate` MUST match.
    3. The `catalogId` points to the Gemini Enterprise custom catalog containing WebFrameSrcdoc.
    4. The `htmlContent` property is passed as an A2UI literalString wrapper.

    Args:
        html_content: The full self-contained HTML5 document string.
        surface_id: Optional unique surface ID. If omitted, a unique ID is generated.
        height: Sizing in pixels (default: 650).
        title: Optional title for the triggering card / side panel header.
        subtitle: Optional subtitle description.
        root_id: Component ID for the root WebFrameSrcdoc component.
        catalog_id: Catalog URI (default: A2UI_V08_GE_CUSTOM_CATALOG_URI).

    Returns:
        List of two A2UI message dictionaries: [beginRendering, surfaceUpdate].
    """
    if not html_content or not html_content.strip():
        raise ValueError("html_content cannot be empty for WebFrame surface.")

    if not surface_id:
        surface_id = f"surface_{uuid.uuid4().hex[:12]}"

    begin_rendering = {
        "beginRendering": {
            "surfaceId": surface_id,
            "catalogId": catalog_id,
            "root": root_id,
        }
    }

    webframe_component: Dict[str, Any] = {
        COMPONENT_WEB_FRAME_SRCDOC: {
            "htmlContent": {"literalString": html_content},
            "height": height,
            "cardTitle": title or "Interactive Analytics Dashboard",
            "cardDescription": subtitle or "Ad-hoc Excel Analytical Breakdown",
            "cardIcon": "analytics",
            "autoOpen": True,
        }
    }

    surface_update = {
        "surfaceUpdate": {
            "surfaceId": surface_id,
            "components": [
                {
                    "id": root_id,
                    "component": webframe_component,
                },
            ],
        }
    }

    # Strict structural validation
    assert (
        begin_rendering["beginRendering"]["root"]
        == surface_update["surfaceUpdate"]["components"][0]["id"]
    ), "Root component ID in beginRendering must match first component ID in surfaceUpdate"

    assert (
        begin_rendering["beginRendering"]["surfaceId"]
        == surface_update["surfaceUpdate"]["surfaceId"]
    ), "surfaceId must be identical across beginRendering and surfaceUpdate"

    return [begin_rendering, surface_update]


def create_a2ui_inline_part(msg: Dict[str, Any]) -> types.Part:
    """Wraps an individual A2UI message into a types.Part with inline_data
    and text/plain MIME type matching the Discovery Engine Assistant Service envelope.

    Args:
        msg: A single A2UI message dictionary (e.g. beginRendering or surfaceUpdate).

    Returns:
        types.Part carrying the encoded A2A DataPart envelope.
    """
    wrapped_payload = {
        "data": msg,
        "metadata": {"mimeType": A2UI_MIME_TYPE},
    }
    raw_envelope = f"<a2a_datapart_json>{json.dumps(wrapped_payload)}</a2a_datapart_json>".encode("utf-8")
    return types.Part(
        inline_data=types.Blob(
            data=raw_envelope,
            mime_type="text/plain",
        )
    )


def build_v09_canvas_surface(
    html_content: str,
    surface_id: Optional[str] = None,
    height: int = 700,
    title: str = "Interactive Analytics Canvas",
) -> List[Dict[str, Any]]:
    """Builds an A2UI v0.9 composite message sequence (beginRendering + surfaceUpdate)
    utilizing Canvas for side-panel surface presentation with nested IFrameSrcdoc.

    Args:
        html_content: The full self-contained HTML5 document string.
        surface_id: Optional unique surface ID.
        height: Sizing in pixels (default: 700).
        title: Title rendered on the Canvas side panel header.

    Returns:
        List of two A2UI message dictionaries: [beginRendering, surfaceUpdate].
    """
    if not surface_id:
        surface_id = f"canvas_surface_{uuid.uuid4().hex[:12]}"

    canvas_root_id = "canvas_root"
    iframe_id = "canvas_iframe"

    begin_rendering = {
        "beginRendering": {
            "surfaceId": surface_id,
            "catalogId": A2UI_V09_COMPOSITE_CATALOG_URI,
            "root": canvas_root_id,
        }
    }

    surface_update = {
        "surfaceUpdate": {
            "surfaceId": surface_id,
            "components": [
                {
                    "id": canvas_root_id,
                    "component": {
                        COMPONENT_CANVAS: {
                            "title": {"literalString": title},
                            "children": {"explicitList": [iframe_id]},
                            "isSidePanelSurface": True,
                        }
                    },
                },
                {
                    "id": iframe_id,
                    "component": {
                        COMPONENT_IFRAME_SRCDOC: {
                            "htmlContent": {"literalString": html_content},
                            "height": height,
                        }
                    },
                },
            ],
        }
    }

    return [begin_rendering, surface_update]


def wrap_messages_as_a2a_parts(a2ui_messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Wraps a list of A2UI messages into A2A DataPart structures with the
    official Gemini Enterprise MIME type `application/json+a2ui`.

    Args:
        a2ui_messages: List of A2UI operations (beginRendering, surfaceUpdate, etc.).

    Returns:
        List of A2A DataPart dictionaries.
    """
    parts = []
    for msg in a2ui_messages:
        parts.append({
            "kind": "data",
            "metadata": {"mimeType": A2UI_MIME_TYPE},
            "data": msg,
        })
    return parts
