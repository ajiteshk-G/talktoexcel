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

"""Serve the reasoning_engine ``{class_method, input}`` contract over HTTP.

Exists to guarantee support for the Vertex AI Console Playground and Gemini
Enterprise (via ADK registration), which both invoke the engine through this
contract. Agent Engine forwards calls to ``/api/reasoning_engine`` (sync) and
``/api/stream_reasoning_engine`` (streaming); dispatch is limited to the
:class:`AdkApp` ``register_operations()`` methods so the wire output matches a
packaged Agent Engine.
"""

from typing import Any, Optional
import base64
import datetime
import inspect
import json
import logging

from fastapi import FastAPI, HTTPException, Request, encoders, responses
from vertexai.agent_engines.templates.adk import AdkApp

from app.app_utils import services
from app.excel_plugin import sanitize_message_dict
from app.ingestion import sanitize_user_id

logger = logging.getLogger(__name__)


def serialize_event_for_json(event: Any) -> str:
    """Safely serializes an event to a JSON string, handling types.Part, Pydantic models, datetimes, and bytes."""
    if isinstance(event, str):
        return event

    def safe_json_default(obj):
        if hasattr(obj, "model_dump"):
            return obj.model_dump(mode="json", exclude_none=True)
        if hasattr(obj, "to_dict"):
            try:
                return obj.to_dict()
            except Exception:
                pass
        if isinstance(obj, (bytes, bytearray)):
            return base64.b64encode(obj).decode("utf-8")
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        try:
            return encoders.jsonable_encoder(obj)
        except Exception:
            return str(obj)

    return json.dumps(event, default=safe_json_default)



def extract_caller_user_id(request: Request, passed_user_id: Optional[str] = None) -> str:
    """Extracts caller identity from Google IAP / Cloud headers, bearer JWT, or passed_user_id."""
    for h in [
        "x-goog-authenticated-user-email",
        "x-goog-user-email",
        "x-forwarded-email",
        "x-user-email",
        "x-user-id",
    ]:
        val = request.headers.get(h)
        if val:
            if ":" in val:
                val = val.split(":")[-1]
            return sanitize_user_id(val)

    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        parts = token.split(".")
        if len(parts) >= 2:
            try:
                payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
                payload_json = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
                email = (
                    payload_json.get("email")
                    or payload_json.get("sub")
                    or payload_json.get("preferred_username")
                )
                if email:
                    return sanitize_user_id(email)
            except Exception:
                pass

    return sanitize_user_id(passed_user_id)


def attach_reasoning_engine_routes(app: FastAPI) -> None:
    """Register reasoning_engine routes that dispatch to an AdkApp."""
    runtime: AdkApp | None = None
    streaming_methods: set[str] = set()
    sync_methods: set[str] = set()

    def get_runtime() -> AdkApp:
        nonlocal runtime, streaming_methods, sync_methods
        if runtime is None:
            from app.agent import app as adk_app

            # Reuse the process-wide services so sessions created here are
            # visible to the adk_api and A2A paths, and vice versa (see services.py).
            runtime = AdkApp(
                app=adk_app,
                session_service_builder=services.get_session_service,
                artifact_service_builder=services.get_artifact_service,
            )
            runtime.set_up()
            operations = runtime.register_operations()
            streaming_methods = set(operations.get("stream", [])) | set(
                operations.get("async_stream", [])
            )
            sync_methods = set(operations.get("", [])) | set(
                operations.get("async", [])
            )
        return runtime

    def resolve_method(class_method: str, *, streaming: bool):
        rt = get_runtime()
        allowed = streaming_methods if streaming else sync_methods
        if class_method not in allowed:
            raise HTTPException(
                status_code=404,
                detail=f"Unsupported reasoning_engine method: {class_method!r}",
            )
        return getattr(rt, class_method)

    @app.post("/api/stream_reasoning_engine")
    async def stream_query(request: Request) -> responses.StreamingResponse:
        body = await request.json()
        class_method = body.get("class_method", "")
        method = resolve_method(class_method, streaming=True)
        input_kwargs = body.get("input") or {}
        user_id = extract_caller_user_id(request, input_kwargs.get("user_id"))

        if class_method == "streaming_agent_run_with_events":
            req_str = input_kwargs.get("request_json", "{}")
            try:
                req_obj = json.loads(req_str) if isinstance(req_str, str) else req_str
                req_user = extract_caller_user_id(request, req_obj.get("user_id"))
                req_obj["user_id"] = req_user
                if "message" in req_obj:
                    req_obj["message"] = sanitize_message_dict(req_obj["message"], req_user)
                req_str = json.dumps(req_obj)
            except Exception:
                pass
            call_kwargs = {"request_json": req_str}
        else:
            call_kwargs = dict(input_kwargs)
            sig = inspect.signature(method)
            has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            if "user_id" in sig.parameters or has_varkw:
                call_kwargs["user_id"] = user_id
            if "message" in call_kwargs:
                call_kwargs["message"] = sanitize_message_dict(call_kwargs["message"], user_id)
            if "session_events" in call_kwargs and isinstance(call_kwargs["session_events"], list):
                call_kwargs["session_events"] = [
                    sanitize_message_dict(ev, user_id) for ev in call_kwargs["session_events"]
                ]
            if not has_varkw:
                call_kwargs = {k: v for k, v in call_kwargs.items() if k in sig.parameters}

        async def generator():
            try:
                async for event in method(**call_kwargs):
                    yield serialize_event_for_json(event) + "\n"
            except Exception as e:
                logger.exception(f"Error in stream_reasoning_engine generator: {e}")
                raise

        return responses.StreamingResponse(
            content=generator(), media_type="application/json"
        )

    @app.post("/api/reasoning_engine")
    async def query(request: Request) -> responses.Response:
        body = await request.json()
        class_method = body.get("class_method", "")
        method = resolve_method(class_method, streaming=False)
        input_kwargs = body.get("input") or {}
        user_id = extract_caller_user_id(request, input_kwargs.get("user_id"))

        if class_method == "agent_run_with_events":
            req_str = input_kwargs.get("request_json", "{}")
            try:
                req_obj = json.loads(req_str) if isinstance(req_str, str) else req_str
                req_user = extract_caller_user_id(request, req_obj.get("user_id"))
                req_obj["user_id"] = req_user
                if "message" in req_obj:
                    req_obj["message"] = sanitize_message_dict(req_obj["message"], req_user)
                req_str = json.dumps(req_obj)
            except Exception:
                pass
            call_kwargs = {"request_json": req_str}
        else:
            call_kwargs = dict(input_kwargs)
            sig = inspect.signature(method)
            has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            if "user_id" in sig.parameters or has_varkw:
                call_kwargs["user_id"] = user_id
            if "message" in call_kwargs:
                call_kwargs["message"] = sanitize_message_dict(call_kwargs["message"], user_id)
            if "session_events" in call_kwargs and isinstance(call_kwargs["session_events"], list):
                call_kwargs["session_events"] = [
                    sanitize_message_dict(ev, user_id) for ev in call_kwargs["session_events"]
                ]
            if not has_varkw:
                call_kwargs = {k: v for k, v in call_kwargs.items() if k in sig.parameters}

        output = (
            await method(**call_kwargs)
            if inspect.iscoroutinefunction(method)
            else method(**call_kwargs)
        )
        return responses.Response(
            content=serialize_event_for_json({"output": output}),
            media_type="application/json",
        )

