"""Local preparation checks; never reserve quota or contact a provider."""
from apps.accounts.access import AccessError


def require_consultation(customer):
    if not customer.notes.strip():
        raise AccessError('AI_INPUT_REQUIRED', '먼저 상담내용에 고객의 관심·질문·약속 등 실제 상담 내용을 입력하고 저장해 주세요. 고객명·연락처만으로는 AI를 생성하지 않습니다.', 422)


def configuration_help(config):
    if config.reason == 'AI_CONFIG_PERMISSIONS':
        return '관리자가 서버 AI 설정 파일의 접근 권한을 확인해야 합니다.'
    if config.reason == 'AI_CONFIG_FILE_REQUIRED':
        return '관리자가 서버의 AI 설정 파일 연결을 확인해야 합니다.'
    if not config.enabled:
        return '관리자가 무료 등급과 현재 프로젝트 한도를 확인한 뒤 AI를 활성화해야 합니다.'
    if not config.configured:
        return '관리자가 서버의 API 키·제공자·모델 설정을 확인해야 합니다.'
    if config.provider != 'gemini' or config.model != 'gemini-3.5-flash-lite' or config.usage_tier != 'free':
        return '무료 Gemini 3.5 Flash-Lite 설정이 필요합니다. 유료 사용 승인 금액은 $0입니다.'
    if not config.free_tier_confirmed:
        return '관리자가 해당 프로젝트의 무료 등급을 확인해야 합니다. 확인 전에는 AI를 사용하지 않습니다.'
    if not config.free_project_id or min(config.free_rpm, config.free_tpm, config.free_rpd) <= 0 or config.free_limits_model != config.model:
        return '관리자가 같은 모델의 현재 프로젝트 무료 RPM·입력 TPM·RPD 한도를 확인해 설정해야 합니다.'
    return '관리자가 무료 AI 연결 설정과 직원 추론 설정을 확인해야 합니다.'
