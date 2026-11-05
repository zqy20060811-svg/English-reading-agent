"""个人电子书（阶段A）测试。

- TestPersonalParser：EPUB/TXT 解析与安全防护（纯单元，始终运行）
- TestPersonalBooksDB：多用户隔离 / 去重 / 删除清理 / 阅读进度（需要 PostgreSQL）

运行：python -m pytest tests/test_personal_books.py -v
"""

import asyncio
import io
import uuid
import zipfile

import pytest
from fastapi import HTTPException

from app.services import personal_parser
from app.services.personal_parser import ParseError, parse_upload


# ================= 测试数据构造 =================

_CH1 = (
    "<html><head><title>ch1</title></head><body>"
    "<h1>Chapter One</h1><p>The quick brown fox jumps over the lazy dog. "
    "It was a bright cold day in April, and the clocks were striking thirteen.</p>"
    "<p>Second paragraph with some more English words to make the text plausible.</p>"
    "</body></html>"
)
_CH2 = (
    "<html><head><title>ch2</title></head><body>"
    "<h2>Chapter Two</h2><p>Another chapter begins here with different content. "
    "Reading practice requires a reasonable amount of text in each section.</p>"
    "</body></html>"
)

_CONTAINER = """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>My Test Book</dc:title>
    <dc:creator>Jane Doe</dc:creator>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
    <item id="img" href="cover.jpg" media-type="image/jpeg"/>
  </manifest>
  <spine><itemref idref="c1"/><itemref idref="c2"/></spine>
</package>"""


def _build_epub(extra_entries: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("META-INF/container.xml", _CONTAINER)
        zf.writestr("OEBPS/content.opf", _OPF)
        zf.writestr("OEBPS/ch1.xhtml", _CH1)
        zf.writestr("OEBPS/ch2.xhtml", _CH2)
        for name, content in (extra_entries or {}).items():
            zf.writestr(name, content)
    return buf.getvalue()


# ================= 解析器（纯单元） =================


class TestPersonalParser:
    def test_epub_metadata_and_chapter_order(self):
        book = parse_upload("book.epub", _build_epub())
        assert book.title == "My Test Book"
        assert book.author == "Jane Doe"
        assert book.language == "en"
        assert book.source_type == "epub"
        assert len(book.chapters) == 2
        # spine 顺序：第 1 章对应 ch1.xhtml
        assert book.chapters[0][0] == "Chapter One"
        assert "quick brown fox" in book.chapters[0][1]
        assert book.chapters[1][0] == "Chapter Two"
        # 脚本与样式内容不得进入正文
        assert "<p>" not in book.chapters[0][1]

    def test_epub_skips_script_and_style(self):
        html = (
            "<html><head><style>.a{color:red}</style></head><body>"
            "<h1>Title</h1><script>alert('x')</script>"
            "<p>Visible words only should remain here.</p></body></html>"
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("META-INF/container.xml", _CONTAINER)
            zf.writestr("OEBPS/content.opf", _OPF)
            zf.writestr("OEBPS/ch1.xhtml", html)
            zf.writestr("OEBPS/ch2.xhtml", _CH2)
        book = parse_upload("x.epub", buf.getvalue())
        body = book.chapters[0][1]
        assert "alert" not in body
        assert "color:red" not in body
        assert "Visible words only" in body

    def test_txt_utf8_with_chapters(self):
        # 每章正文需超过切分器最小词数（150），且章节标题需相隔足够行数（>8），
        # 否则会被当作目录重复标题或过小章节合并
        body = "\n\n".join(["It was the best of times, it was the worst of times."] * 20)
        text = f"CHAPTER I. The Beginning\n\n{body}\n\nCHAPTER II. The End\n\n{body}"
        book = parse_upload("novel.txt", text.encode("utf-8"))
        assert book.source_type == "txt"
        assert len(book.chapters) >= 2
        assert book.chapters[0][0] == "The Beginning"
        assert book.chapters[1][0] == "The End"
        assert book.title == "novel"

    def test_txt_fallback_encoding(self):
        # 非 UTF-8 编码（cp1252 弯引号）应能兜底解码而不是直接报错
        text = "CHAPTER I\n\nIt wasn\u2019t a dark night, the story begins here with words.\n"
        book = parse_upload("a.txt", text.encode("cp1252"))
        assert "dark night" in book.chapters[0][1]

    def test_txt_empty_rejected(self):
        with pytest.raises(ParseError, match="为空或过短"):
            parse_upload("empty.txt", b"   \n\n  ")

    def test_extension_mismatch_rejected(self):
        # 内容是 ZIP/EPUB，但扩展名是 .txt
        with pytest.raises(ParseError, match="与扩展名不符"):
            parse_upload("fake.txt", _build_epub())

    def test_unsupported_extension_rejected(self):
        with pytest.raises(ParseError, match="仅支持"):
            parse_upload("book.pdf", b"whatever")

    def test_non_epub_zip_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("random.txt", "no container here")
        with pytest.raises(ParseError, match="META-INF/container.xml"):
            parse_upload("bad.epub", buf.getvalue())

    def test_zip_entry_count_limit(self, monkeypatch):
        monkeypatch.setattr(personal_parser, "EPUB_MAX_ENTRIES", 10)
        with pytest.raises(ParseError, match="文件数量过多"):
            parse_upload("bomb.epub", _build_epub({"f%d.txt" % i: b"x" for i in range(20)}))

    def test_zip_single_entry_size_limit(self, monkeypatch):
        monkeypatch.setattr(personal_parser, "EPUB_MAX_ENTRY_BYTES", 1024)
        with pytest.raises(ParseError, match="单个文件过大"):
            parse_upload("bomb.epub", _build_epub({"OEBPS/big.bin": b"A" * 4096}))

    def test_zip_declared_size_lie_is_caught(self, monkeypatch):
        """声明大小合规但实际解压超限（伪造 central directory）也要拦截"""
        monkeypatch.setattr(personal_parser, "EPUB_MAX_ENTRY_BYTES", 1024)
        payload = b"B" * 4096
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("META-INF/container.xml", _CONTAINER)
            zf.writestr("OEBPS/content.opf", _OPF)
            zf.writestr("OEBPS/ch1.xhtml", _CH1)
            zf.writestr("OEBPS/ch2.xhtml", _CH2)
            info = zipfile.ZipInfo("OEBPS/lie.bin")
            info.file_size = 10  # 伪造声明大小
            zf.writestr(info, payload)
        with pytest.raises((ParseError, zipfile.BadZipFile)):
            parse_upload("lie.epub", buf.getvalue())

    def test_path_traversal_entry_rejected(self):
        with pytest.raises(ParseError, match="非法路径"):
            parse_upload("evil.epub", _build_epub({"../evil.xhtml": b"<html></html>"}))

    # ---------- 内嵌封面 ----------

    # JPEG 文件头魔数（解析器只透传字节，不校验图片内容）
    _JPG = b"\xff\xd8\xff\xe0" + b"fakejpeg" * 8

    def _epub_with_cover(self, marker: str) -> bytes:
        """在标准 OPF 上打封面标记补丁：properties 或 meta 两种方式"""
        opf = _OPF.replace(
            '<item id="img" href="cover.jpg" media-type="image/jpeg"/>',
            f'<item id="img" href="cover.jpg" media-type="image/jpeg" {marker}/>',
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("META-INF/container.xml", _CONTAINER)
            zf.writestr("OEBPS/content.opf", opf)
            zf.writestr("OEBPS/ch1.xhtml", _CH1)
            zf.writestr("OEBPS/ch2.xhtml", _CH2)
            zf.writestr("OEBPS/cover.jpg", self._JPG)
        return buf.getvalue()

    def test_epub_cover_extracted_via_properties(self):
        """EPUB3 风格：manifest properties 含 cover-image"""
        book = parse_upload("book.epub", self._epub_with_cover('properties="cover-image"'))
        assert book.cover is not None
        data, media = book.cover
        assert data == self._JPG
        assert media == "image/jpeg"

    def test_epub_cover_extracted_via_meta(self):
        """EPUB2 风格：<meta name="cover" content="img">"""
        opf = _OPF.replace(
            "</metadata>",
            '<meta name="cover" content="img"/></metadata>',
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("META-INF/container.xml", _CONTAINER)
            zf.writestr("OEBPS/content.opf", opf)
            zf.writestr("OEBPS/ch1.xhtml", _CH1)
            zf.writestr("OEBPS/ch2.xhtml", _CH2)
            zf.writestr("OEBPS/cover.jpg", self._JPG)
        book = parse_upload("book.epub", buf.getvalue())
        assert book.cover is not None and book.cover[0] == self._JPG

    def test_epub_without_cover_reference(self):
        """manifest 里有图片但没有任何封面引用 → 无封面，不影响解析"""
        book = parse_upload("book.epub", _build_epub())
        assert book.cover is None

    def test_epub_cover_non_image_media_ignored(self):
        """封面引用指向非图片 media-type → 忽略"""
        opf = _OPF.replace(
            '<item id="img" href="cover.jpg" media-type="image/jpeg"/>',
            '<item id="img" href="cover.jpg" media-type="text/html" properties="cover-image"/>',
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("META-INF/container.xml", _CONTAINER)
            zf.writestr("OEBPS/content.opf", opf)
            zf.writestr("OEBPS/ch1.xhtml", _CH1)
            zf.writestr("OEBPS/ch2.xhtml", _CH2)
            zf.writestr("OEBPS/cover.jpg", self._JPG)
        assert parse_upload("book.epub", buf.getvalue()).cover is None


# ================= 数据库集成 =================

DB_READY = None


def _db_available() -> bool:
    global DB_READY
    if DB_READY is not None:
        return DB_READY

    async def _ping():
        from app.db.database import engine

        await engine.dispose()  # 先清掉上一事件循环遗留的连接池
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))

    try:
        asyncio.run(_ping())
        DB_READY = True
    except Exception:
        DB_READY = False
    return DB_READY


requires_db = pytest.mark.skipif(
    not _db_available(), reason="PostgreSQL 不可用，跳过个人书籍数据库测试"
)


def _run(coro):
    async def _wrap():
        from app.db.database import engine

        await engine.dispose()
        await coro

    return asyncio.run(_wrap())


async def _make_user(db):
    """直接插入测试用户（绕过注册/邮箱验证）"""
    from app.models.user import User

    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f"pbu_{suffix}",
        email=f"pbu_{suffix}@test.local",
        hashed_password="x",
        email_verified=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, user.username


@requires_db
class TestPersonalBooksDB:
    def test_cover_store_isolation_and_cleanup(self, tmp_path, monkeypatch):
        """带内嵌封面的 EPUB：封面落盘、has_cover 标记、B 不可读、删除清理"""
        from pathlib import Path

        async def main():
            from app.core.config import get_settings
            from app.db.database import AsyncSessionLocal
            from app.services.personal_book_service import PersonalBookService

            settings = get_settings()
            monkeypatch.setattr(settings, "PERSONAL_BOOKS_DIR", str(tmp_path))
            jpg = b"\xff\xd8\xff\xe0" + b"coverdata" * 4
            epub = TestPersonalParser()._epub_with_cover('properties="cover-image"')
            # 把假 JPEG 替换成测试字节：直接重建
            import zipfile as _zf
            buf = io.BytesIO()
            with _zf.ZipFile(buf, "w", _zf.ZIP_DEFLATED) as zf:
                src = _zf.ZipFile(io.BytesIO(epub))
                for name in src.namelist():
                    zf.writestr(name, jpg if name.endswith("cover.jpg") else src.read(name))

            async with AsyncSessionLocal() as db:
                user_a, _ = await _make_user(db)
                user_b, _ = await _make_user(db)
                service = PersonalBookService(db)

                book, _ = await service.create_book(user_a, "withcover.epub", buf.getvalue())
                assert book.cover_ext == ".jpg"
                assert book.has_cover is True

                # 封面文件已落盘，内容一致；本人可获取路径
                cover_file = (
                    Path(tmp_path) / str(user_a.id) / "covers" / f"{book.id}.jpg"
                )
                assert cover_file.exists() and cover_file.read_bytes() == jpg
                got = await service.get_cover_path(user_a, book.id)
                assert Path(got) == cover_file

                # B 无权访问封面
                with pytest.raises(HTTPException) as exc:
                    await service.get_cover_path(user_b, book.id)
                assert exc.value.status_code == 404

                # 无封面的书 404
                plain, _ = await service.create_book(user_a, "plain.epub", _build_epub())
                with pytest.raises(HTTPException) as exc:
                    await service.get_cover_path(user_a, plain.id)
                assert exc.value.status_code == 404

                # 删除书籍 → 封面文件一并清理
                await service.delete_book(user_a, book.id)
                assert not cover_file.exists()

        _run(main())

    def test_upload_isolation_progress_and_delete(self, tmp_path, monkeypatch):
        """用户 A 上传后可读；用户 B 全接口不可见；删除后数据与文件清理干净"""
        async def main():
            from sqlalchemy import func, select

            from app.core.config import get_settings
            from app.db.database import AsyncSessionLocal
            from app.models.personal_book import PersonalBook
            from app.models.personal_book_chapter import PersonalBookChapter
            from app.models.personal_reading_progress import PersonalReadingProgress
            from app.services.personal_book_service import PersonalBookService

            settings = get_settings()
            monkeypatch.setattr(settings, "PERSONAL_BOOKS_DIR", str(tmp_path))

            async with AsyncSessionLocal() as db:
                user_a, _ = await _make_user(db)
                user_b, _ = await _make_user(db)
                service = PersonalBookService(db)

                book, dup = await service.create_book(user_a, "mine.epub", _build_epub())
                assert dup is False
                assert book.chapter_count == 2

                # A 能读列表/详情/目录/正文
                assert len(await service.list_books(user_a)) == 1
                detail = await service.get_book(user_a, book.id)
                assert detail.title == "My Test Book"
                chapters = await service.list_chapters(user_a, book.id)
                assert [c.chapter_index for c in chapters] == [1, 2]
                ch = await service.get_chapter(user_a, book.id, 2)
                assert "Another chapter begins" in ch.content

                # B 访问 A 的书一律 404（不区分「不存在」与「他人的书」）
                for call in (
                    service.get_book(user_b, book.id),
                    service.list_chapters(user_b, book.id),
                    service.get_chapter(user_b, book.id, 1),
                    service.get_progress(user_b, book.id),
                ):
                    with pytest.raises(HTTPException) as exc:
                        await call
                    assert exc.value.status_code == 404
                assert await service.list_books(user_b) == []

                # B 不能写 A 的书的进度
                from app.schemas.personal_book import PersonalProgressUpdate
                with pytest.raises(HTTPException) as exc:
                    await service.save_progress(
                        user_b, book.id,
                        PersonalProgressUpdate(chapter_index=1, char_offset=5, percent=10),
                    )
                assert exc.value.status_code == 404

                # A 保存/读取进度
                saved = await service.save_progress(
                    user_a, book.id,
                    PersonalProgressUpdate(chapter_index=2, char_offset=10, page_index=3, percent=42.5),
                )
                assert saved.chapter_index == 2 and saved.percent == 42.5
                assert (await service.get_progress(user_a, book.id)).page_index == 3

                # 越界章号 / 超长偏移被拒绝
                with pytest.raises(HTTPException) as exc:
                    await service.save_progress(
                        user_a, book.id,
                        PersonalProgressUpdate(chapter_index=99, char_offset=1, percent=1),
                    )
                assert exc.value.status_code == 400
                with pytest.raises(HTTPException) as exc:
                    await service.save_progress(
                        user_a, book.id,
                        PersonalProgressUpdate(chapter_index=1, char_offset=10**9, percent=1),
                    )
                assert exc.value.status_code == 400

                # 删除：章节 / 进度 / 书 / 磁盘文件全部清理
                path = book.storage_path
                await service.delete_book(user_a, book.id)
                assert (await db.execute(
                    select(func.count()).select_from(PersonalBookChapter)
                    .where(PersonalBookChapter.personal_book_id == book.id)
                )).scalar() == 0
                assert (await db.execute(
                    select(func.count()).select_from(PersonalReadingProgress)
                    .where(PersonalReadingProgress.personal_book_id == book.id)
                )).scalar() == 0
                assert (await db.execute(
                    select(func.count()).select_from(PersonalBook)
                    .where(PersonalBook.id == book.id)
                )).scalar() == 0
                assert not __import__("pathlib").Path(path).exists()

                # 删除后 A 也无法再访问
                with pytest.raises(HTTPException) as exc:
                    await service.get_book(user_a, book.id)
                assert exc.value.status_code == 404

                # 清理测试用户，避免污染
                from app.models.user import User
                await db.execute(User.__table__.delete().where(
                    User.id.in_([user_a.id, user_b.id])
                ))
                await db.commit()

        _run(main())

    def test_duplicate_upload_reuses_record(self, tmp_path, monkeypatch):
        """同一用户重复上传相同内容：命中已有记录，不新增书、不新增文件"""
        async def main():
            import pathlib

            from app.core.config import get_settings
            from app.db.database import AsyncSessionLocal
            from app.services.personal_book_service import PersonalBookService

            settings = get_settings()
            monkeypatch.setattr(settings, "PERSONAL_BOOKS_DIR", str(tmp_path))

            async with AsyncSessionLocal() as db:
                user, _ = await _make_user(db)
                service = PersonalBookService(db)
                first, dup1 = await service.create_book(user, "a.txt", b"CHAPTER I\n\n" + b"word " * 200)
                assert dup1 is False
                files_before = list(pathlib.Path(tmp_path).rglob("*"))

                second, dup2 = await service.create_book(user, "a-copy.txt", b"CHAPTER I\n\n" + b"word " * 200)
                assert dup2 is True
                assert second.id == first.id
                assert len(await service.list_books(user)) == 1
                assert list(pathlib.Path(tmp_path).rglob("*")) == files_before

                # 用户 B 上传相同内容：互不影响（去重只在同一用户内生效）
                user_b, _ = await _make_user(db)
                other, dup3 = await service.create_book(
                    user_b, "a.txt", b"CHAPTER I\n\n" + b"word " * 200
                )
                assert dup3 is False and other.id != first.id

                await db.delete(first)
                await db.delete(other)
                from app.models.user import User
                await db.execute(User.__table__.delete().where(
                    User.id.in_([user.id, user_b.id])
                ))
                await db.commit()

        _run(main())

    def test_cover_backfill_for_legacy_books(self, tmp_path, monkeypatch):
        """存量书籍（cover_ext 为空）首次访问列表时惰性补提取封面"""
        from pathlib import Path

        async def main():
            from app.core.config import get_settings
            from app.db.database import AsyncSessionLocal
            from app.services.personal_book_service import PersonalBookService

            settings = get_settings()
            monkeypatch.setattr(settings, "PERSONAL_BOOKS_DIR", str(tmp_path))
            jpg = b"\xff\xd8\xff\xe0" + b"legacy" * 4
            import zipfile as _zf
            epub = TestPersonalParser()._epub_with_cover('properties="cover-image"')
            buf = io.BytesIO()
            with _zf.ZipFile(buf, "w", _zf.ZIP_DEFLATED) as zf:
                src = _zf.ZipFile(io.BytesIO(epub))
                for name in src.namelist():
                    zf.writestr(name, jpg if name.endswith("cover.jpg") else src.read(name))

            async with AsyncSessionLocal() as db:
                user, _ = await _make_user(db)
                service = PersonalBookService(db)

                book, _ = await service.create_book(user, "legacy.epub", buf.getvalue())
                # 模拟旧数据：清掉 cover_ext 与封面文件
                book.cover_ext = None
                await db.commit()
                cover_file = Path(tmp_path) / str(user.id) / "covers" / f"{book.id}.jpg"
                if cover_file.exists():
                    cover_file.unlink()
                await db.refresh(book)
                assert book.cover_ext is None

                # 首次访问列表 → 自动回填
                rows = await service.list_books(user)
                assert rows[0].has_cover is True
                assert cover_file.exists() and cover_file.read_bytes() == jpg

                # 再次访问：已回填，不再重复处理（仍正常返回）
                rows = await service.list_books(user)
                assert rows[0].has_cover is True

                # 清理
                await service.delete_book(user, book.id)
                from app.models.user import User
                await db.execute(User.__table__.delete().where(User.id == user.id))
                await db.commit()

        _run(main())
