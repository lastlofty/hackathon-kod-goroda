from typing import Any

from fastapi import HTTPException, status
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError


def validate_schema(schema: dict[str, Any]) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid attribute_schema: {exc.message}",
        ) from exc


def validate_attributes(attributes: dict[str, Any], schema: dict[str, Any]) -> None:
    if not schema:
        return
    try:
        Draft202012Validator(schema).validate(attributes)
    except ValidationError as exc:
        path = ".".join(str(item) for item in exc.absolute_path)
        location = f" at {path}" if path else ""
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid attributes{location}: {exc.message}",
        ) from exc
