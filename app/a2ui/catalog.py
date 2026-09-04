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

"""A2UI Catalog constants, component identifiers, and schemas for Gemini Enterprise."""

from typing import Final

# A2UI Protocol Extensions
A2UI_V08_EXTENSION_URI: Final[str] = "https://a2ui.org/a2a-extension/a2ui/v0.8"
A2UI_V09_EXTENSION_URI: Final[str] = "https://a2ui.org/a2a-extension/a2ui/v0.9"

# Standard & Gemini Enterprise Custom Catalog URIs
A2UI_V08_STANDARD_CATALOG_URI: Final[str] = (
    "https://a2ui.org/specification/v0_8/standard_catalog_definition.json"
)
A2UI_V08_GE_CUSTOM_CATALOG_URI: Final[str] = (
    "https://www.gstatic.com/vertexaisearch/a2ui/v0_8/gemini_enterprise_custom_catalog.json"
)
A2UI_V09_COMPOSITE_CATALOG_URI: Final[str] = (
    "https://www.gstatic.com/vertexaisearch/a2ui/v0_9/gemini_enterprise_composite_catalog.json"
)

# A2UI Wire MIME Types
A2UI_MIME_TYPE: Final[str] = "application/json+a2ui"
A2UI_STANDARD_MIME_TYPE: Final[str] = "application/a2ui+json"

# A2UI Component Names (v0.8 Standard & GE Custom)
COMPONENT_WEB_FRAME_SRCDOC: Final[str] = "WebFrameSrcdoc"
COMPONENT_WEB_FRAME_URL: Final[str] = "WebFrameUrl"
COMPONENT_COLUMN: Final[str] = "Column"
COMPONENT_ROW: Final[str] = "Row"
COMPONENT_CARD: Final[str] = "Card"
COMPONENT_TEXT: Final[str] = "Text"
COMPONENT_BUTTON: Final[str] = "Button"
COMPONENT_DIVIDER: Final[str] = "Divider"

# A2UI Component Names (v0.9 Composite & Canvas)
COMPONENT_CANVAS: Final[str] = "Canvas"
COMPONENT_IFRAME_SRCDOC: Final[str] = "IFrameSrcdoc"
COMPONENT_IFRAME_URL: Final[str] = "IFrameUrl"

# A2UI Action Type for bidirectional postMessage communication
A2UI_ACTION_TYPE: Final[str] = "a2ui_action"
