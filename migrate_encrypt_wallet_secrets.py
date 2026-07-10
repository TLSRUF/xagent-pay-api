"""
지갑 시크릿(seed) 암호화 마이그레이션 스크립트

keys/api_keys.json에 평문으로 저장된 기존 wallet_seed 필드를
SECRET_ENCRYPTION_KEY(Fernet)로 암호화한 wallet_seed_encrypted 필드로 옮긴다.

사용법:
    python migrate_encrypt_wallet_secrets.py

- SECRET_ENCRYPTION_KEY가 .env에 없으면 새로 생성해서 .env에 추가한다.
  (기존에 이미 암호화된 데이터가 있다면 반드시 그 키를 그대로 써야 하므로,
   이 스크립트를 두 번째로 돌리는 상황이라면 .env의 SECRET_ENCRYPTION_KEY를 지우지 말 것.)
- 원본 keys/api_keys.json은 실행 전 타임스탬프가 붙은 .bak 파일로 백업한다.
- 실제 시크릿 값은 로그에 출력하지 않는다.
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv, set_key
from cryptography.fernet import Fernet

ENV_FILE = Path(".env")
KEYS_FILE = Path("keys") / "api_keys.json"


def ensure_encryption_key() -> str:
    """SECRET_ENCRYPTION_KEY를 .env에서 읽거나, 없으면 새로 생성해 추가한다."""
    load_dotenv(ENV_FILE)
    key = os.getenv("SECRET_ENCRYPTION_KEY")

    if key:
        print("SECRET_ENCRYPTION_KEY: 기존 값을 사용합니다 (.env).")
        return key

    if not ENV_FILE.exists():
        raise SystemExit(f"오류: {ENV_FILE} 파일이 없습니다. 먼저 .env를 생성하세요.")

    new_key = Fernet.generate_key().decode()
    set_key(str(ENV_FILE), "SECRET_ENCRYPTION_KEY", new_key)
    print(f"SECRET_ENCRYPTION_KEY가 없어서 새로 생성해 {ENV_FILE}에 추가했습니다.")
    print("이 키를 분실하면 이미 암호화된 지갑 시크릿을 복호화할 수 없습니다. 반드시 별도로 백업하세요.")
    return new_key


def backup_keys_file() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = KEYS_FILE.with_suffix(f".json.bak.{timestamp}")
    shutil.copy2(KEYS_FILE, backup_path)
    print(f"원본 백업: {backup_path}")
    return backup_path


def migrate():
    if not KEYS_FILE.exists():
        print(f"{KEYS_FILE}가 없습니다. 마이그레이션할 데이터가 없어 종료합니다.")
        return

    encryption_key = ensure_encryption_key()
    fernet = Fernet(encryption_key.encode())

    with open(KEYS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not data:
        print("keys/api_keys.json에 레코드가 없습니다. 종료합니다.")
        return

    backup_keys_file()

    migrated = 0
    already_encrypted = 0
    no_wallet = 0

    for key_hash, record in data.items():
        if "wallet_seed_encrypted" in record and record.get("wallet_seed_encrypted"):
            # 이미 암호화된 레코드 — 건드리지 않음
            already_encrypted += 1
            record.pop("wallet_seed", None)  # 혹시 남아있는 평문 필드가 있다면 제거
            continue

        plaintext_seed = record.pop("wallet_seed", None)

        if not plaintext_seed:
            # 지갑이 없는 키(플랫폼 공용 지갑 사용) — 필드만 정리
            record["wallet_seed_encrypted"] = None
            no_wallet += 1
            continue

        record["wallet_seed_encrypted"] = fernet.encrypt(plaintext_seed.encode()).decode()
        migrated += 1

    with open(KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print()
    print("마이그레이션 완료:")
    print(f"  - 평문 → 암호화 변환: {migrated}건")
    print(f"  - 이미 암호화되어 있던 레코드: {already_encrypted}건")
    print(f"  - 전용 지갑 없는 레코드(변경 없음): {no_wallet}건")
    print(f"  - 총 레코드: {len(data)}건")
    print()
    print("주의: 백업 파일(keys/*.json.bak.*)에는 원본 평문 시크릿이 그대로 들어있습니다.")
    print("keys/api_keys.json에서 암호화가 정상 동작하는지 확인한 뒤에는 백업 파일을 삭제하세요.")


if __name__ == "__main__":
    migrate()
