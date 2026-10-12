import requests
from fastapi import HTTPException, status
from fastapi.concurrency import run_in_threadpool

from app.core.config import get_settings

# 请求超时（秒）
REQUEST_TIMEOUT = 60

SYSTEM_PROMPT = (
    "You are an English reading assistant. Answer questions about English books, "
    "vocabulary and reading comprehension clearly and helpfully. "
    "Reply in the same language as the user's question."
)


class LLMService:
    """DeepSeek 大模型调用业务逻辑"""

    async def ask(self, question: str) -> str:
        """调用 DeepSeek chat 接口回答问题。"""
        settings = get_settings()
        if not settings.DEEPSEEK_API_KEY:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "DeepSeek API Key 未配置，请在 .env 中填写 DEEPSEEK_API_KEY",
            )

        payload = {
            "model": settings.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
        }
        # requests 为同步库，放入线程池避免阻塞事件循环
        return await run_in_threadpool(self._request_chat, payload)

    @staticmethod
    def _request_chat(payload: dict) -> str:
        settings = get_settings()
        try:
            resp = requests.post(
                f"{settings.DEEPSEEK_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data["choices"][0]["message"]["content"].strip()
            if not answer:
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, "大模型返回内容为空")
            return answer
        except HTTPException:
            raise
        except requests.HTTPError as exc:
            detail = exc.response.text[:200] if exc.response is not None else str(exc)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"DeepSeek 接口错误：{detail}")
        except requests.RequestException as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"无法连接 DeepSeek：{exc}")


def get_llm_service() -> LLMService:
    return LLMService()
