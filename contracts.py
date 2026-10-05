"""Small dependency-free validator for the project's JSON contracts."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class ContractError(ValueError):
    pass


def load_contract(stage):
    registry = json.loads((ROOT / "config/prompt-stages.json").read_text(encoding="utf-8"))
    entry = next((item for item in registry["stages"] if item["id"] == stage), None)
    if entry is None:
        raise ContractError("未知阶段: %s" % stage)
    return json.loads((ROOT / entry["output_schema"]).read_text(encoding="utf-8"))


def validate_contract(value, schema, path="$"):
    if "enum" in schema and value not in schema["enum"]:
        raise ContractError("%s 不在允许值中" % path)

    expected = schema.get("type")
    allowed = expected if isinstance(expected, list) else [expected] if expected else []
    type_matches = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if allowed and not any(type_matches[kind](value) for kind in allowed):
        raise ContractError("%s 类型错误，应为 %s" % (path, "/".join(allowed)))

    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            raise ContractError("%s 缺少字段: %s" % (path, ", ".join(missing)))
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = [key for key in value if key not in properties]
            if extras:
                raise ContractError("%s 包含未定义字段: %s" % (path, ", ".join(extras)))
        for key, item in value.items():
            if key in properties:
                validate_contract(item, properties[key], "%s.%s" % (path, key))

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ContractError("%s 项目数量不足" % path)
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ContractError("%s 项目数量过多" % path)
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                validate_contract(item, item_schema, "%s[%d]" % (path, index))

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise ContractError("%s 文本过短" % path)
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise ContractError("%s 文本过长" % path)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ContractError("%s 小于最小值" % path)
        if "maximum" in schema and value > schema["maximum"]:
            raise ContractError("%s 大于最大值" % path)
    return value


def validate_stage_output(stage, value):
    return validate_contract(value, load_contract(stage))
