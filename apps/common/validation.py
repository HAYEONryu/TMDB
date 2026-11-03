import re
from django.core.exceptions import ValidationError


def normalize_phone(value):
    if not isinstance(value, str):
        raise ValidationError("전화번호는 문자열로 입력해 주세요.")
    normalized = re.sub(r"[\s-]", "", value)
    if not re.fullmatch(r"010[0-9]{8}", normalized):
        raise ValidationError("010으로 시작하는 11자리 전화번호를 입력해 주세요.")
    return normalized


def site_name_key(value):
    return "".join(value.split()).lower()
