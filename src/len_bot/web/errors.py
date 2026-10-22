"""面板 HTTP 错误正文，以及不含输入正文的请求校验错误。"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, JsonValue
from starlette.exceptions import HTTPException


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str
    code: str | None = None
    data: JsonValue = None


class PanelError(BaseModel):
    detail: ErrorDetail


def error_response(status: int, detail: str | dict, *, headers: dict | None = None) -> JSONResponse:
    value = ErrorDetail(message=detail) if isinstance(detail, str) else ErrorDetail.model_validate(detail)
    payload = value.model_dump(mode='json')
    if 'data' not in value.model_fields_set:
        del payload['data']
    return JSONResponse({'detail': payload}, status_code=status, headers=headers)


def install_panel_errors(app: FastAPI) -> None:
    app.router.responses.update({status: {'model': PanelError}
                                 for status in (400, 401, 403, 404, 405, 409, 413, 415, 422, 429, 500, 502, 503)})

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        return error_response(error.status_code, error.detail, headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, error: RequestValidationError):
        errors = [{'loc': list(item['loc']), 'msg': item['msg'], 'type': item['type']}
                  for item in error.errors()]
        message = '; '.join(f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in errors)
        return error_response(422, {'message': message, 'code': 'validation_error', 'data': {'errors': errors}})
