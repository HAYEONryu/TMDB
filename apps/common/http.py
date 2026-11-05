from functools import wraps
import json
import uuid
from django.http import JsonResponse
from django.db import OperationalError,DatabaseError
from django.core.exceptions import RequestDataTooBig
from apps.accounts.access import AccessError, api_error


def json_object(request):
    try:
        value = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        raise AccessError("VALIDATION_ERROR", "JSON 형식을 확인해 주세요.", 422)
    if not isinstance(value, dict):
        raise AccessError("VALIDATION_ERROR", "객체 형식으로 보내 주세요.", 422)
    return value


def identifier(value, *, nullable=False):
    if value is None and nullable:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise AccessError("VALIDATION_ERROR", "식별자가 올바르지 않습니다.", 422)


def api_errors(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except AccessError as exc:
            return api_error(exc.code, exc.message, exc.status, exc.fields)
        except OperationalError:
            return api_error("TEMPORARY_UNAVAILABLE", "잠시 후 같은 요청으로 다시 시도해 주세요.", 503)
        except DatabaseError:
            return api_error("TEMPORARY_UNAVAILABLE", "저장을 완료하지 못했습니다. 같은 요청으로 다시 확인해 주세요.", 503)
        except RequestDataTooBig:
            return api_error("PAYLOAD_TOO_LARGE", "요청 크기 상한을 넘었습니다. 변경 행을 나누어 저장해 주세요.", 413)
    return wrapped
