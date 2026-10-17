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


# RAG 问答用的系统提示词：要求只基于检索证据回答，证据不足时明确说明
READING_SYSTEM_PROMPT = (
    "You are an English reading assistant. The user is reading a book, and some "
    "relevant excerpts retrieved from the book are provided below.\n"
    "Rules:\n"
    "1. Answer the question based ONLY on the excerpts provided. "
    "Quote the original text when helpful.\n"
    "2. If the excerpts do not contain enough information to answer, say so "
    "explicitly (e.g. \"提供的片段中没有足够信息\") and briefly explain what is "
    "missing. Do NOT invent or supplement content that is not in the excerpts.\n"
    "3. Reply in the same language as the user's question."
)

# 单章正文最长注入字符数（防止超长章节超出模型上下文，超出则截断保留开头）
MAX_CONTEXT_CHARS = 50000


class LLMService:
    """DeepSeek 大模型调用业务逻辑"""

    async def ask(self, question: str) -> str:
        """调用 DeepSeek chat 接口回答问题。"""
        return await run_in_threadpool(
            self._request_chat,
            self._build_payload(SYSTEM_PROMPT, question),
        )

    async def ask_with_context(self, question: str, context: str) -> str:
        """基于给定上下文（如 RAG 检索的证据片段）回答问题。"""
        if not context:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "上下文内容为空")
        context = context[:MAX_CONTEXT_CHARS]
        user_content = (
            f"Retrieved excerpts from the book:\n\n{context}\n\n---\n\nQuestion: {question}"
        )
        return await run_in_threadpool(
            self._request_chat,
            self._build_payload(READING_SYSTEM_PROMPT, user_content),
        )

    @staticmethod
    def _build_payload(system_prompt: str, user_content: str) -> dict:
        settings = get_settings()
        if not settings.DEEPSEEK_API_KEY:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "DeepSeek API Key 未配置，请在 .env 中填写 DEEPSEEK_API_KEY",
            )
        return {
            "model": settings.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }

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
