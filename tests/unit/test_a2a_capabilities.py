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

"""Unit tests for A2A capabilities advertisement and A2UI extension registration."""

from app.app_utils.a2a import _default_capabilities


def test_a2a_advertises_a2ui_extension():
    """Verify that default agent capabilities advertise A2UI v0.8 extension."""
    capabilities = _default_capabilities()
    assert capabilities.streaming is True
    assert capabilities.extensions is not None
    assert len(capabilities.extensions) >= 2

    # Locate A2UI extension
    a2ui_ext = next(
        (ext for ext in capabilities.extensions if "a2ui" in ext.uri.lower()),
        None,
    )
    assert a2ui_ext is not None
    assert a2ui_ext.uri == "https://a2ui.org/a2a-extension/a2ui/v0.8"
    assert a2ui_ext.params is not None
    assert "supportedCatalogIds" in a2ui_ext.params
    assert (
        "https://a2ui.org/specification/v0_8/standard_catalog_definition.json"
        in a2ui_ext.params["supportedCatalogIds"]
    )
    assert (
        "https://www.gstatic.com/vertexaisearch/a2ui/v0_8/gemini_enterprise_custom_catalog.json"
        in a2ui_ext.params["supportedCatalogIds"]
    )
