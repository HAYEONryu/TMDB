from datetime import datetime, timezone as datetime_timezone
from io import BytesIO
from pathlib import PurePosixPath
import re
import warnings
from zipfile import ZipFile, BadZipFile
from xml.etree.ElementTree import ParseError
from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import iterparse
from openpyxl.utils.cell import column_index_from_string
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.styles.numbers import is_datetime
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.comments import Comment
from openpyxl.xml import DEFUSEDXML
from openpyxl.utils.exceptions import InvalidFileException
from django.conf import settings
from django.core.exceptions import ValidationError
from apps.accounts.access import AccessError
from apps.common.validation import normalize_phone
from apps.customers.models import Customer
from apps.customers.queries import KST

LEGACY_HEADERS = ["담당직원명", "고객명", "고객 연락처", "통화결과", "방문예약 날짜", "계약여부", "상담기타내용", "재콜일정", "주택상황"]
HEADERS = ["고객명", "연락처", "고객 거주지", "주택상황", "비고", "관리자 비고"]
HEADER_HINTS = [
    "선택 · 문자 최대 100자\n빈 칸 가능\n예: 가상고객",
    "필수 · 010 시작 11자리\n텍스트로 입력\n예: 010-0000-0000",
    "선택 · 문자 최대 200자\n예: 서울 강서구",
    "선택 · 문자 최대 200자\n예: 자가/전세/월세/기타",
    "선택 · 문자 최대 10,000자\n기존 상담기타내용과 별도\n줄바꿈 가능 · 수식 금지",
    "선택 · 문자 최대 10,000자\n관리자만 조회·수정\n직원에게 노출되지 않음",
]
TEMPLATE_HEADERS = [f"{title}\n{hint}" for title, hint in zip(HEADERS, HEADER_HINTS)]
HEADER_INSTRUCTIONS = [
    "선택. 문자 최대 100자. 빈 칸도 등록할 수 있습니다. 예: 가상고객. 앞뒤 공백은 제거합니다.",
    "필수. 010으로 시작하는 11자리 텍스트. 예: 010-0000-0000 또는 01000000000. "
    "하이픈·공백은 제거해 검사합니다. 숫자로 저장해 앞자리 0이 빠지면 복원하지 않습니다. "
    "전체 현장의 중복 연락처는 등록하지 않습니다. 휴지통 고객은 중복 검사에서 제외합니다.",
    "선택. 고객 거주지를 자유 입력하는 문자 최대 200자. 예: 서울 강서구. 앞뒤 공백은 제거합니다.",
    "선택. 자유 입력 문자 최대 200자. 예: 미확인, 자가, 전세, 월세, 기타. 빈 칸도 허용합니다.",
    "선택. 문자 최대 10,000자. 기존 상담기타내용과 별도인 비고입니다. 줄바꿈 가능. 수식은 사용할 수 없습니다.",
    "선택. 문자 최대 10,000자. 관리자만 조회·수정합니다. 직원 화면·API·상담 이력·AI 입력에 제공하지 않습니다. 줄바꿈 가능. 수식은 사용할 수 없습니다.",
]
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
# Invalid dates/links can cause library warnings containing raw cell input.
# These are converted to row/file errors below rather than sent to server stderr.
warnings.filterwarnings("ignore", module=r"openpyxl(?:\..*)?")


def file_error(code, message):
    raise AccessError(code, message, 422)


def template_bytes():
    book = Workbook()
    sheet = book.active
    sheet.title = "고객 등록"
    sheet.append(TEMPLATE_HEADERS)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = "A1:F1"
    for cell, width in zip(sheet[1], [26, 30, 30, 30, 42, 42]):
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor="245C4E")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        sheet.column_dimensions[cell.column_letter].width = width
    sheet.row_dimensions[1].height = 112
    for column in "ABCDEF":
        sheet.column_dimensions[column].number_format = "@"
        sheet[f"{column}2"].number_format = "@"
    for cell, title, instruction in zip(sheet[1], HEADERS, HEADER_INSTRUCTIONS):
        cell.comment = Comment(instruction, "TM 고객관리")
        cell.comment.width, cell.comment.height = 380, 140
        column = cell.column_letter
        validation = DataValidation(type="custom", formula1="TRUE", allow_blank=True)
        validation.promptTitle, validation.prompt = title, instruction
        validation.showInputMessage = True
        sheet.add_data_validation(validation)
        validation.add(f"{column}2:{column}10001")
    output = BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def check_archive(data):
    with ZipFile(BytesIO(data)) as archive:
        entries = archive.infolist()
        names = [item.filename for item in entries]
        if len(entries) > 1000 or len(set(names)) != len(names) or sum(item.file_size for item in entries) > MAX_EXPANDED_BYTES:
            file_error("UNSAFE_XLSX", "엑셀 파일의 내부 크기나 구성이 처리 한도를 넘었습니다. 입력 양식에 첫 시트 데이터만 복사해 다시 업로드해 주세요.")
        for item in entries:
            path = PurePosixPath(item.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in item.filename or item.flag_bits & 1:
                file_error("UNSAFE_XLSX", "이 엑셀 파일의 내부 구성을 지원하지 않습니다.")
            if "vbaproject" in item.filename.lower() or item.filename.lower().endswith("workbook.bin"):
                file_error("MACRO_NOT_ALLOWED", "매크로 파일은 업로드할 수 없습니다.")
        content = archive.read("[Content_Types].xml")
        if b"macroenabled" in content.lower() or b"vnd.ms-excel.sheet.binary" in content.lower():
            file_error("MACRO_NOT_ALLOWED", "매크로·바이너리 파일은 업로드할 수 없습니다.")


def blank(value):
    return value is None or isinstance(value, str) and not value.strip()


def extra_columns(data, sheet_path, shared_strings, width):
    """Validate sparse XML bounds without materializing 16,384 cells per row."""
    extra = set()
    previous = 0
    with ZipFile(BytesIO(data)) as archive, archive.open(sheet_path) as source:
        for _, element in iterparse(source, events=("end",)):
            if element.tag.endswith("}row"):
                number = int(element.attrib.get("r", previous+1))
                if not previous < number <= 1048576:
                    file_error("INVALID_XLSX", "Excel 행 번호가 올바르지 않습니다.")
                previous = number
                for cell in element:
                    address = cell.attrib.get("r", "")
                    match = re.fullmatch(r"([A-Z]+)([0-9]+)", address)
                    if not match or int(match[2]) != number:
                        file_error("INVALID_XLSX", "Excel 셀 주소가 올바르지 않습니다.")
                    column = column_index_from_string(match[1])
                    if not 1 <= column <= 16384:
                        file_error("INVALID_XLSX", "Excel 열 번호가 올바르지 않습니다.")
                    if column > width:
                        for child in cell:
                            if child.tag.endswith("}f"):
                                extra.add(number)
                            elif child.tag.endswith("}v"):
                                value=shared_strings[int(child.text)] if cell.attrib.get("t")=="s" else child.text
                                if not blank(value):extra.add(number)
                            elif child.tag.endswith("}is") and not blank("".join(node.text or "" for node in child.iter() if node.tag.endswith("}t"))):
                                extra.add(number)
                element.clear()
    return extra


def text_value(value, label, maximum, *, required=False, trim=True):
    if blank(value):
        if required:
            raise ValueError(f"{label}을 입력해 주세요.")
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{label}은 문자열로 입력해 주세요.")
    value = value.strip() if trim else value.replace("\r\n", "\n").replace("\r", "\n")
    if len(value) > maximum:
        raise ValueError(f"{label}은 {maximum:,}자까지 입력할 수 있습니다.")
    return value


def excel_datetime(cell):
    value = cell.value
    if blank(value):
        return None
    if isinstance(value, datetime):
        if is_datetime(cell.number_format) != "datetime":
            raise ValueError("날짜와 시각이 모두 표시되는 Excel 서식을 사용해 주세요.")
        parsed = value.replace(tzinfo=KST)
    elif isinstance(value, str):
        value = re.sub(r"\s*\([월화수목금토일](?:요일)?\)\s*", " ", value.strip())
        value = re.sub(r"\s+", " ", value).strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", value):
            raise ValueError("날짜와 시각을 YYYY-MM-DD HH:mm 형식으로 함께 입력해 주세요.")
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    else:
        raise ValueError("날짜와 시각을 함께 입력해 주세요. 숫자 날짜는 추측하지 않습니다.")
    try:
        parsed.astimezone(datetime_timezone.utc)
    except (ValueError,OverflowError):
        raise ValueError("날짜·시각 범위를 확인해 주세요.") from None
    return parsed.isoformat()


def parse_row(cells, *, legacy=False):
    values = [cell.value for cell in cells]
    if any(cell.data_type == "f" for cell in cells):
        raise ValueError("수식 셀은 사용할 수 없습니다.")
    if any(cell.data_type == "e" for cell in cells):
        raise ValueError("Excel 오류값이 포함되어 있습니다.")
    if legacy and not blank(values[0]):
        raise ValueError("담당직원명은 비워 주세요. 등록 고객은 미할당 상태입니다.")
    name = text_value(values[1 if legacy else 0], "고객명", 100)
    phone_input = values[2 if legacy else 1]
    if not isinstance(phone_input, str):
        raise ValueError("연락처를 텍스트로 입력해 주세요. 숫자로 소실된 앞자리 0은 복원하지 않습니다.")
    try:
        phone = normalize_phone(phone_input)
    except ValidationError:
        raise ValueError("연락처는 010으로 시작하는 11자리여야 합니다.") from None
    if not legacy:
        return {"customer_name":name, "phone_normalized":phone,
            "residence":text_value(values[2], "고객 거주지", 200),
            "housing_status":text_value(values[3], "주택상황", 200),
            "memo":text_value(values[4], "비고", 10000, trim=False),
            "admin_notes":text_value(values[5], "관리자 비고", 10000, trim=False),
            "notes":"", "call_result":None, "visit_at":None,
            "callback_due_at":None, "contract_status":"UNKNOWN"}
    call = text_value(values[3], "통화결과", 20)
    contract = text_value(values[5], "계약여부", 20)
    calls = {label: code for code, label in Customer.CallResult.choices}
    contracts = {label: code for code, label in Customer.ContractStatus.choices}
    if call and call not in calls or contract and contract not in contracts:
        raise ValueError("통화결과·계약여부는 양식의 허용값을 사용해 주세요.")
    return {"customer_name":name, "phone_normalized":phone, "call_result":calls.get(call),
        "visit_at":excel_datetime(cells[4]), "contract_status":contracts.get(contract, "UNKNOWN"),
        "notes":text_value(values[6], "상담기타내용", 10000, trim=False),
        "callback_due_at":excel_datetime(cells[7]), "housing_status":text_value(values[8], "주택상황", 200)}


def parse_upload(upload):
    """No disk extraction, formula evaluation, external-link loading or retained original."""
    book = None
    try:
        if not upload.name.lower().endswith(".xlsx"):
            file_error("INVALID_FILE_TYPE", ".xlsx 파일만 업로드할 수 있습니다.")
        data = upload.read(settings.IMPORT_MAX_BYTES + 1)
        if len(data) > settings.IMPORT_MAX_BYTES:
            raise AccessError("FILE_TOO_LARGE", "파일은 10MB까지 업로드할 수 있습니다.", 413)
        if not DEFUSEDXML:
            raise AccessError("IMPORT_UNAVAILABLE", "엑셀 파서의 보호 설정을 확인해 주세요.", 503)
        check_archive(data)
        book = load_workbook(BytesIO(data), read_only=True, data_only=False, keep_links=False)
        if not book.worksheets:
            file_error("INVALID_HEADER", "첫 워크시트를 확인해 주세요.")
        sheet = book.worksheets[0]
        sheet.reset_dimensions()
        rows = sheet.iter_rows(min_col=1,max_col=9)
        header = next(rows, ())
        while header and blank(header[-1].value):
            header = header[:-1]
        # The first line is the stable column title. Later lines are guidance,
        # so files remain valid when examples or explanatory text are updated.
        titles = [cell.value.split("\n", 1)[0].rstrip("\r") if isinstance(cell.value, str) else cell.value for cell in header]
        legacy = titles == LEGACY_HEADERS
        width = 9 if legacy else 6
        extra = extra_columns(data, sheet._worksheet_path, sheet._shared_strings, width)
        if (1 in extra or titles not in [HEADERS, LEGACY_HEADERS]
                or any(cell.data_type == "f" for cell in header)):
            file_error("INVALID_HEADER", "첫 행은 고객명·연락처·고객 거주지·주택상황·비고·관리자 비고 순서여야 합니다. 기존 9열 양식도 지원합니다.")
        results, candidates, seen = [], [], set()
        for row_number, cells in enumerate(rows, 2):
            if row_number not in extra and all(blank(cell.value) for cell in cells):
                continue
            if len(results) >= settings.IMPORT_MAX_ROWS:
                file_error("TOO_MANY_ROWS", "빈 행을 제외한 데이터는 10,000행까지 가능합니다.")
            padded = list(cells)
            # EmptyCell objects keep the same interface as real cells.
            if len(padded) < 9:
                from openpyxl.cell.read_only import EMPTY_CELL
                padded += [EMPTY_CELL] * (9-len(padded))
            values = [cell.value for cell in padded]
            name_index, phone_index = (1, 2) if legacy else (0, 1)
            name, phone = str(values[name_index] or ""), str(values[phone_index] if values[phone_index] is not None else "")
            if any(isinstance(value, str) and len(value) > 32767 for value in values):
                file_error("INVALID_XLSX", "Excel 셀의 최대 문자 수를 넘은 파일입니다.")
            result = {"row_number":row_number,"success":False,"customer_name":name,"phone_input":phone,"error_code":"","reason":""}
            try:
                if row_number in extra:
                    raise ValueError(f"입력 양식의 {width}개 열 밖에 값이 있습니다.")
                normalized = parse_row(padded[:width], legacy=legacy)
                if normalized["phone_normalized"] in seen:
                    result.update(error_code="DUPLICATE_IN_FILE",reason="파일에서 먼저 나온 유효한 연락처 행과 중복됩니다.")
                else:
                    seen.add(normalized["phone_normalized"])
                    candidates.append((row_number, normalized))
                    result["success"] = True
            except ValueError as exc:
                result.update(error_code="INVALID_ROW", reason=str(exc))
            results.append(result)
        if not results:
            file_error("EMPTY_FILE", "등록할 데이터가 없습니다. 첫 행 아래에 고객정보를 입력해 주세요.")
        return results, candidates
    except AccessError:
        raise
    except (BadZipFile, KeyError, ValueError, TypeError, OSError, ParseError, DefusedXmlException, OverflowError, IndexError, RuntimeError, EOFError, InvalidFileException):
        file_error("INVALID_XLSX", "엑셀 파일을 읽을 수 없습니다. 입력 양식으로 다시 저장해 주세요.")
    finally:
        if book:
            book.close()
        upload.close()
