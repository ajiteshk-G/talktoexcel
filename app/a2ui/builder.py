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

import uuid
from typing import Any, Dict, List, Optional

from app.a2ui.catalog import (
    A2UI_MIME_TYPE,
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
    root_id: str = "iframe_root",
    webframe_id: str = "iframe_widget",
) -> List[Dict[str, Any]]:
    """Builds the canonical A2UI v0.8 message sequence (beginRendering + surfaceUpdate)
    for rendering an isolated, sandboxed WebFrameSrcdoc in Gemini Enterprise.

    Critical A2UI Invariants Enforced:
    1. The root component ID declared in `beginRendering.root` MUST be byte-identical
       to the ID of the root component in `surfaceUpdate.components`.
    2. The `surfaceId` in `beginRendering` and `surfaceUpdate` MUST match.
    3. The `htmlContent` property is passed as an A2UI literalString wrapper.

    Args:
        html_content: The full self-contained HTML5 document string.
        surface_id: Optional unique surface ID. If omitted, a unique ID is generated.
        height: Sizing in pixels (default: 650).
        root_id: Component ID for the outer Column container.
        webframe_id: Component ID for the WebFrameSrcdoc component.

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
            "catalogId": A2UI_V08_STANDARD_CATALOG_URI,
            "root": root_id,
        }
    }

    surface_update = {
        "surfaceUpdate": {
            "surfaceId": surface_id,
            "components": [
                {
                    "id": root_id,
                    "component": {
                        COMPONENT_COLUMN: {
                            "children": {"explicitList": [webframe_id]},
                            "alignment": "stretch",
                        }
                    },
                },
                {
                    "id": webframe_id,
                    "component": {
                        COMPONENT_WEB_FRAME_SRCDOC: {
                            "htmlContent": {"literalString": html_content},
                            "height": height,
                        }
                    },
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
