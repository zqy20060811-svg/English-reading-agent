"""封面图本地缓存单元测试（假 httpx 响应，不依赖网络/数据库）。"""

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from app.services import cover_service as cs
from app.services.cover_service import ensure_cover_file, local_cover_path, media_type_of

PNG_BYTES = b"\x89PNG fake cover bytes"
JPG_BYTES = b"\xff\xd8 fake cover bytes"


class FakeResponse:
    def __init__(self, status_code=200, content=JPG_BYTES, content_type="image/jpeg"):
        self.status_code = status_code
        self.content = content
        self.headers = {"content-type": content_type}


class FakeAsyncClient:
    """记录下载次数的假 httpx 客户端；resp 为预设响应或异常"""

    download_count = 0
    resp: FakeResponse | Exception = FakeResponse()

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        type(self).download_count += 1
        r = type(self).resp
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def cover_env(tmp_path, monkeypatch):
    """临时封面目录 + 可配置的假下载客户端"""
    d = tmp_path / "covers"
    d.mkdir()
    monkeypatch.setattr(cs, "covers_dir", lambda: d)
    monkeypatch.setattr(cs.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.download_count = 0
    FakeAsyncClient.resp = FakeResponse()
    return d


def test_download_then_local_hit(cover_env):
    """首次从源站下载并落盘；第二次直接本地命中，不再访问网络"""

    async def run():
        path = await ensure_cover_file(7, "https://covers.openlibrary.org/b/id/7-L.jpg")
        again = await ensure_cover_file(7, "https://covers.openlibrary.org/b/id/7-L.jpg")
        return path, again

    path, again = asyncio.run(run())
    assert path.exists() and path.read_bytes() == JPG_BYTES
    assert FakeAsyncClient.download_count == 1  # 只下载一次
    assert again == path


def test_local_cache_hit_skips_download(cover_env):
    """已有落盘文件时直接返回，完全不发网络请求"""
    (cover_env / "9.jpg").write_bytes(JPG_BYTES)
    path = asyncio.run(ensure_cover_file(9, "https://covers.openlibrary.org/b/id/9-L.jpg"))
    assert path.name == "9.jpg"
    assert FakeAsyncClient.download_count == 0


def test_invalid_content_type_rejected(cover_env):
    """非图片响应拒绝落盘并抛 404，由前端渐变占位兜底"""
    FakeAsyncClient.resp = FakeResponse(content=b"<html>error page</html>", content_type="text/html")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ensure_cover_file(3, "https://covers.openlibrary.org/b/id/3-L.jpg"))
    assert exc.value.status_code == 404


def test_source_unreachable_rejected(cover_env):
    """源站网络异常抛 404，不影响书库正常展示"""
    FakeAsyncClient.resp = httpx.ConnectTimeout("timeout")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ensure_cover_file(4, "https://covers.openlibrary.org/b/id/4-L.jpg"))
    assert exc.value.status_code == 404


def test_png_saved_with_png_extension(cover_env):
    """按响应 content-type 落盘对应扩展名，供正确的 media type 返回"""
    FakeAsyncClient.resp = FakeResponse(content=PNG_BYTES, content_type="image/png")
    path = asyncio.run(ensure_cover_file(5, "https://example.com/5.png"))
    assert path.name == "5.png"
    assert media_type_of(path) == "image/png"


def test_local_cover_path_scans_all_extensions(cover_env):
    """local_cover_path 能扫到任意支持格式的已缓存封面"""
    assert local_cover_path(11) is None
    (cover_env / "11.webp").write_bytes(b"webp")
    assert local_cover_path(11) == cover_env / "11.webp"
