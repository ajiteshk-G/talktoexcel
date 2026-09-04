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

"""Process-wide ADK session/artifact services shared by every serving surface.

Registered under ``shared://`` so the ADK web routes, the A2A path, and the
reasoning_engine adapter share one instance: a session created on any surface
is visible to the others.
"""

from __future__ import annotations

import functools
import os

from google.adk.artifacts import GcsArtifactService, InMemoryArtifactService
from google.adk.cli.service_registry import get_service_registry
from google.adk.cli.utils.service_factory import create_session_service_from_options

SESSION_SERVICE_URI = "shared://session"
ARTIFACT_SERVICE_URI = "shared://artifact"

_AGENT_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


@functools.cache
def get_session_service():
    """Process-wide session service shared across every serving surface."""
    if uri := os.environ.get("SESSION_SERVICE_URI"):
        return create_session_service_from_options(
            base_dir=_AGENT_DIR, session_service_uri=uri
        )
    if agent_engine_id := os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID"):
        from google.adk.sessions.vertex_ai_session_service import VertexAiSessionService

        loc = os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_LOCATION")
        if not loc or loc == "global":
            loc = os.environ.get("GOOGLE_CLOUD_REGION") or "us-central1"
        proj = os.environ.get("GOOGLE_CLOUD_PROJECT") or "mb-poc-352009"
        return VertexAiSessionService(
            project=proj,
            location=loc,
            agent_engine_id=agent_engine_id,
        )
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    return InMemorySessionService()


import logging

logger = logging.getLogger(__name__)


@functools.cache
def get_artifact_service():
    """Process-wide artifact service: GCS when a bucket is set, else in-memory."""
    bucket = os.environ.get("LOGS_BUCKET_NAME") or os.environ.get("GCS_DROPZONE_BUCKET")
    if bucket:
        proj = os.environ.get("GOOGLE_CLOUD_PROJECT", "mb-poc-352009")
        try:
            return GcsArtifactService(bucket_name=bucket, project=proj)
        except Exception as e:
            logger.warning(f"Fallback to InMemoryArtifactService: {e}")
    return InMemoryArtifactService()


_registry = get_service_registry()
_registry.register_session_service("shared", lambda uri, **kw: get_session_service())
_registry.register_artifact_service("shared", lambda uri, **kw: get_artifact_service())
