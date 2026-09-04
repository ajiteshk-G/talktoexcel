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

"""A2UI Protocol and WebFrame Components Package for Gemini Enterprise."""

from app.a2ui.builder import (
    build_v09_canvas_surface,
    build_webframe_surface,
    create_a2ui_inline_part,
    wrap_messages_as_a2a_parts,
)
from app.a2ui.catalog import (
    A2UI_ACTION_TYPE,
    A2UI_MIME_TYPE,
    A2UI_STANDARD_MIME_TYPE,
    A2UI_V08_EXTENSION_URI,
    A2UI_V08_STANDARD_CATALOG_URI,
    A2UI_V09_COMPOSITE_CATALOG_URI,
    A2UI_V09_EXTENSION_URI,
    COMPONENT_CANVAS,
    COMPONENT_COLUMN,
    COMPONENT_IFRAME_SRCDOC,
    COMPONENT_IFRAME_URL,
    COMPONENT_WEB_FRAME_SRCDOC,
    COMPONENT_WEB_FRAME_URL,
)
from app.a2ui.templates.dashboard import generate_dashboard_html

__all__ = [
    "A2UI_ACTION_TYPE",
    "A2UI_MIME_TYPE",
    "A2UI_STANDARD_MIME_TYPE",
    "A2UI_V08_EXTENSION_URI",
    "A2UI_V08_STANDARD_CATALOG_URI",
    "A2UI_V09_COMPOSITE_CATALOG_URI",
    "A2UI_V09_EXTENSION_URI",
    "COMPONENT_CANVAS",
    "COMPONENT_COLUMN",
    "COMPONENT_IFRAME_SRCDOC",
    "COMPONENT_IFRAME_URL",
    "COMPONENT_WEB_FRAME_SRCDOC",
    "COMPONENT_WEB_FRAME_URL",
    "build_v09_canvas_surface",
    "build_webframe_surface",
    "create_a2ui_inline_part",
    "generate_dashboard_html",
    "wrap_messages_as_a2a_parts",
]
