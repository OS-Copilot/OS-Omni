"""Shared planner helpers for json/tool-calling action modules."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple


def extract_first_json_object(text: str) -> Optional[str]:
    """Extract the first balanced JSON object from arbitrary text."""

    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]

        start = text.find("{", start + 1)

    return None


def _normalize_action_dict(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize common action key aliases into a dict containing `type`."""

    if "type" in payload and str(payload.get("type", "")).strip():
        normalized = dict(payload)
        normalized["type"] = str(normalized["type"]).strip()
        return normalized

    for alias_key in ("action", "action_type"):
        if alias_key not in payload:
            continue

        alias_value = payload.get(alias_key)
        if isinstance(alias_value, str) and alias_value.strip():
            normalized = dict(payload)
            normalized["type"] = alias_value.strip()
            normalized.pop(alias_key, None)
            return normalized

        if isinstance(alias_value, dict):
            nested = _normalize_action_dict(alias_value)
            if nested is not None:
                normalized = dict(payload)
                normalized.pop(alias_key, None)
                normalized.update(nested)
                return normalized

    return None


def parse_action_from_text(llm_response: str) -> Tuple[Optional[Dict[str, Any]], bool]:
    """Parse the first JSON object containing an action `type` from model text."""

    text = (llm_response or "").strip()
    if not text:
        return None, False

    code_block = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    candidate = code_block.group(1).strip() if code_block else text

    json_str = extract_first_json_object(candidate)
    if not json_str:
        json_str = extract_first_json_object(text)
    if not json_str:
        return None, False

    try:
        action = json.loads(json_str)
    except json.JSONDecodeError:
        return None, False

    if isinstance(action, dict):
        normalized = _normalize_action_dict(action)
        if normalized is not None:
            return normalized, True

    return None, False


def parse_tool_arguments(arguments_text: str) -> Tuple[Dict[str, Any], bool]:
    """Parse tool call arguments as a JSON object."""

    try:
        args = json.loads(arguments_text or "{}")
    except json.JSONDecodeError:
        return {}, False
    if not isinstance(args, dict):
        return {}, False
    return args, True


def _extract_quoted_tokens(text: str) -> List[str]:
    return [m.group(1) for m in re.finditer(r"'([^']+)'", text or "")]


def _looks_like_coordinate_target_param(param_name: str, pinfo: Dict[str, Any]) -> bool:
    lowered_name = str(param_name or "").strip().lower()
    description = str(pinfo.get("description", "") or "").lower()
    return (
        lowered_name == "target"
        or lowered_name.endswith("_target")
        or "[x, y]" in description
        or "pixel coords" in description
        or "normalized coords" in description
        or "{'x': 0.5" in description
        or '{"x": 0.5' in description
    )


def _build_array_schema_from_param_info(pinfo: Dict[str, Any], param_name: str = "") -> Dict[str, Any]:
    description = str(pinfo.get("description", "") or "")
    lower_desc = description.lower()

    items_type = str(pinfo.get("items_type", "") or "").strip().lower()
    if items_type == "string":
        item_schema: Dict[str, Any] = {"type": "string"}
        items_enum = pinfo.get("items_enum")
        if isinstance(items_enum, list) and items_enum:
            item_schema["enum"] = [str(v) for v in items_enum]
        return {"type": "array", "items": item_schema}
    if items_type in {"integer", "number", "boolean", "object"}:
        return {"type": "array", "items": {"type": items_type}}

    if _looks_like_coordinate_target_param(param_name, pinfo):
        return {
            "type": "array",
            "items": {"type": "number"},
            "minItems": 2,
            "maxItems": 2,
        }

    if "modifier" in lower_desc and "key" in lower_desc:
        item_schema = {"type": "string"}
        inferred_enum = _extract_quoted_tokens(description)
        if inferred_enum:
            item_schema["enum"] = inferred_enum
        return {"type": "array", "items": item_schema}

    return {"type": "array", "items": {"type": "string"}}


def _build_object_schema_from_param_info(pinfo: Dict[str, Any], param_name: str = "") -> Dict[str, Any]:
    if _looks_like_coordinate_target_param(param_name, pinfo):
        return {
            "type": "object",
            "properties": {
                "x": {"type": "number"},
                "y": {"type": "number"},
            },
            "required": ["x", "y"],
            "additionalProperties": False,
        }

    return {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }


def _convert_type_to_json_schema(
    type_str: str,
    pinfo: Optional[Dict[str, Any]] = None,
    param_name: str = "",
) -> Dict[str, Any]:
    type_map: Dict[str, Dict[str, Any]] = {
        "string": {"type": "string"},
        "integer": {"type": "integer"},
        "number": {"type": "number"},
        "boolean": {"type": "boolean"},
    }

    raw_types = [t.strip() for t in (type_str or "string").split("|") if t.strip()]
    if not raw_types:
        return {"type": "string"}

    schemas: List[Dict[str, Any]] = []
    param_info = pinfo or {}
    for t in raw_types:
        if t == "array":
            schemas.append(_build_array_schema_from_param_info(param_info, param_name))
        elif t == "object":
            schemas.append(_build_object_schema_from_param_info(param_info, param_name))
        else:
            schemas.append(type_map.get(t, {"type": "string"}))

    if len(schemas) == 1:
        return dict(schemas[0])
    return {"anyOf": schemas}


def build_openai_tools_from_action_schema(action_schema: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert ACTION_SCHEMA into OpenAI-compatible tool declarations."""

    tools: List[Dict[str, Any]] = []

    for action_type, schema in action_schema.items():
        parameters = schema.get("parameters", {}) or {}
        properties: Dict[str, Any] = {}
        required: List[str] = []

        for pname, pinfo in parameters.items():
            p_schema = _convert_type_to_json_schema(
                str(pinfo.get("type", "string")),
                pinfo,
                pname,
            )
            if pinfo.get("description"):
                p_schema["description"] = pinfo["description"]
            if "enum" in pinfo and "anyOf" not in p_schema:
                p_schema["enum"] = pinfo["enum"]
            if "default" in pinfo:
                p_schema["default"] = pinfo["default"]
            properties[pname] = p_schema
            if pinfo.get("required"):
                required.append(pname)

        function_parameters: Dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }
        if required:
            function_parameters["required"] = required

        tools.append(
            {
                "type": "function",
                "function": {
                    "name": action_type,
                    "description": schema.get("description", f"Perform {action_type} action"),
                    "parameters": function_parameters,
                },
            }
        )

    return tools


def extract_openai_tool_names(openai_tools: List[Dict[str, Any]]) -> List[str]:
    """Extract function names from OpenAI-style tool declarations in stable order."""

    names: List[str] = []
    seen = set()

    for tool in openai_tools:
        if not isinstance(tool, dict):
            continue
        function_spec = tool.get("function") or {}
        name = str(function_spec.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)

    return names
