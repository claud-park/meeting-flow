import os

import truststore

truststore.inject_into_ssl()  # macOS 시스템 키체인의 신뢰 인증서를 그대로 사용 (회사 TLS 검사 장비 대응)

import boto3
from botocore.config import Config

def load_config(path="config.env"):
    cfg = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip().strip('"').strip("'").split("#")[0].strip().strip('"')
        cfg[k.strip()] = v.replace("$HOME", os.path.expanduser("~"))
    return cfg

cfg = load_config()
s3 = boto3.client(
    "s3",
    endpoint_url=cfg["NCP_OS_ENDPOINT"],
    aws_access_key_id=cfg["NCP_ACCESS_KEY"],
    aws_secret_access_key=cfg["NCP_SECRET_KEY"],
    region_name="kr-standard",
    config=Config(
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
    ),
)

wav = os.path.expanduser("~/Meetings/2026-07-03_1642_회의.wav")
s3.upload_file(wav, cfg["NCP_BUCKET"], "meetings/test_meeting.wav")
print("업로드 OK: meetings/test_meeting.wav")