#!/usr/bin/env python3
"""解密 Actions 日志中脱敏的私有仓库名称"""
import base64
import hashlib
import os
import sys

SALT = os.environ.get("LOG_MASK_SALT")
if not SALT:
    print("错误：请设置环境变量 LOG_MASK_SALT（与 GitHub Secret 中的值一致）", file=sys.stderr)
    print("本地设置方式：export LOG_MASK_SALT=\"your-salt-here\"", file=sys.stderr)
    sys.exit(1)

key = hashlib.sha256(SALT.encode()).digest()[:16]


def decrypt(masked: str) -> str:
    padded = masked + "=" * (-len(masked) % 8)
    data = base64.b32decode(padded)
    return bytes(
        a ^ b for a, b in zip(data, key * (len(data) // len(key) + 1))
    ).decode()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: LOG_MASK_SALT=xxx python decrypt_log.py <标识> [标识2 ...]", file=sys.stderr)
        sys.exit(1)
    for token in sys.argv[1:]:
        try:
            print(f"{token} → {decrypt(token)}")
        except Exception:
            print(f"{token} → (无法解密)", file=sys.stderr)
