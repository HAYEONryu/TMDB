"""Optional web memory/concurrency tuning. Defaults match the existing image."""
import os


def integer(name, default, minimum, maximum):
    try:
        value=int(os.environ.get(name,str(default)))
    except ValueError:
        raise ValueError(name+' 설정은 정수여야 합니다.') from None
    if not minimum<=value<=maximum:
        raise ValueError(name+' 설정 범위를 확인해 주세요.')
    return value


bind='0.0.0.0:8000'
worker_class='gthread'
workers=integer('TM_WEB_WORKERS',2,1,4)
threads=integer('TM_WEB_THREADS',4,1,8)
max_requests=integer('TM_WEB_MAX_REQUESTS',0,0,1000000)
max_requests_jitter=integer('TM_WEB_MAX_REQUESTS_JITTER',50 if max_requests else 0,0,10000)
accesslog=None
errorlog='-'
control_socket_disable=True
