"""邮箱验证码服务：生成、发送（SMTP 或 console）、Redis 校验"""

import asyncio
import random
import smtplib
from email.mime.text import MIMEText

from redis.asyncio import Redis

from app.core.config import get_settings

# purpose 区分用途：verify=邮箱验证，reset=密码找回
CODE_KEY_PREFIX = "email_code:"
SENT_FLAG_PREFIX = "email_code_sent:"  # 发送冷却标记（60 秒防刷）


def generate_code() -> str:
    """生成 6 位数字验证码"""
    return f"{random.randint(0, 999999):06d}"


async def send_code(email: str, code: str, purpose: str, redis: Redis) -> None:
    """发送验证码：60 秒冷却防刷；SMTP 未配置时 console 输出（开发环境）"""
    sent_flag = SENT_FLAG_PREFIX + f"{purpose}:{email}"
    if await redis.exists(sent_flag):
        raise TooFrequentError
    settings = get_settings()
    body = f"【English Reading Agent】您的验证码是 {code}，10 分钟内有效。（用途：{'邮箱验证' if purpose == 'verify' else '密码找回'}）"
    if settings.SMTP_HOST and settings.SMTP_USER:
        # smtplib 是同步阻塞 IO，放线程池执行避免卡事件循环
        await asyncio.to_thread(_send_via_smtp, email, body, settings)
    else:
        # 开发环境：无 SMTP 配置，验证码直接打印到后端控制台
        print(f"[email:{purpose}] -> {email} code={code}")
    await redis.set(CODE_KEY_PREFIX + f"{purpose}:{email}", code, ex=settings.EMAIL_CODE_TTL)
    await redis.set(sent_flag, "1", ex=60)


class TooFrequentError(Exception):
    """发送过于频繁（60 秒冷却中）"""


def _send_via_smtp(to: str, body: str, settings) -> None:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "English Reading Agent 验证码"
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
    msg["To"] = to
    with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM or settings.SMTP_USER, [to], msg.as_string())


async def verify_code(email: str, code: str, purpose: str, redis: Redis) -> bool:
    """校验验证码：正确则消费掉（一次性），错误返回 False"""
    key = CODE_KEY_PREFIX + f"{purpose}:{email}"
    stored = await redis.get(key)
    if stored is None or stored != code:
        return False
    await redis.delete(key)
    return True
