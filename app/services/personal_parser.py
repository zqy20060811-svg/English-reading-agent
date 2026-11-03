"""个人电子书解析器（EPUB / TXT）：纯函数，不依赖数据库与网络。

安全约束：
- 真实类型按文件内容判定，扩展名只做白名单校验（内容与扩展名不符直接拒绝）
- EPUB 本质是 ZIP：限制条目数、单条目解压大小与总解压大小，防 ZIP Bomb
- 只读不落盘：从 zip 流式读取并设字节上限，不做 extract，杜绝路径穿越写文件
- 不执行脚本、不加载外部资源：HTMLParser 跳过 script/style/head，仅提取可见文本
- 解析失败统一抛 ParseError（携带面向用户的中文原因）
"""

import html
import io
import posixpath
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from app.services.chapter_service import split_chapters

# EPUB 防护阈值
EPUB_MAX_ENTRIES = 2000                 # 压缩包内文件条目上限
EPUB_MAX_ENTRY_BYTES = 30 * 1024 * 1024  # 单个条目解压后上限（30MB）
EPUB_MAX_TOTAL_BYTES = 200 * 1024 * 1024  # 全部条目解压后总上限（200MB）
XML_MAX_BYTES = 5 * 1024 * 1024          # container.xml / OPF 等元数据文件上限

ALLOWED_EXTENSIONS = {".epub", ".txt"}
_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "table", "tr", "td", "th",
    "blockquote", "section", "article", "pre", "figure", "figcaption",
}
_HEADING_TAGS = {"h1", "h2", "h3"}
_SKIP_TAGS = {"script", "style", "head", "title", "meta", "link"}


class ParseError(Exception):
    """解析失败（消息可直接展示给用户）"""


@dataclass
class ParsedBook:
    """解析结果：元数据 + 有序章节正文"""

    title: str
    author: str
    language: str
    source_type: str            # epub / txt
    chapters: list[tuple[str, str]]  # [(章节标题, 正文)]


# ================= 通用工具 =================


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z][A-Za-z'-]*", text))


def _clean_text(text: str) -> str:
    """归一化空白与控制字符：保留段落换行，压缩多余空行"""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[^\S\n]+", " ", text)          # 行内连续空白 → 单空格
    text = re.sub(r"\n{3,}", "\n\n", text)         # 3 个以上换行 → 2 个
    return text.strip()


def _fallback_title(filename: str) -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return stem.strip() or "未命名书籍"


def _decode_text(data: bytes) -> str:
    """文本解码：优先 BOM，再依次尝试常见编码（GBK 系中文文本兜底）"""
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig")
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    for enc in ("utf-8", "gb18030", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")  # 最后兜底，不会失败


def detect_type(filename: str, data: bytes) -> tuple[str, str]:
    """按内容判定真实类型，并与扩展名交叉校验。

    返回 (扩展名类型, 真实类型)，不一致时抛 ParseError。
    """
    ext = posixpath.splitext(filename.lower())[1]
    if ext not in ALLOWED_EXTENSIONS:
        raise ParseError("仅支持 EPUB 与 TXT 格式的电子书")
    actual = "epub" if zipfile.is_zipfile(io.BytesIO(data)) else "txt"
    if ext.lstrip(".") != actual:
        raise ParseError(
            f"文件内容与扩展名不符：扩展名为 {ext}，但内容是"
            + (" EPUB/ZIP 压缩包" if actual == "epub" else " 纯文本")
        )
    return ext.lstrip("."), actual


# ================= HTML 正文提取 =================


class _TextExtractor(HTMLParser):
    """提取 XHTML 可见文本：跳过脚本/样式/头部，块级标签换行，记录首个标题"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.heading: str = ""
        self._skip_depth = 0
        self._heading_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _HEADING_TAGS:
            self._heading_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _HEADING_TAGS and self._heading_depth:
            self._heading_depth -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._heading_depth and not self.heading.strip():
            self.heading += data
        self.parts.append(data)

    def text(self) -> str:
        return _clean_text(html.unescape("".join(self.parts)))

    def heading_text(self) -> str:
        return _clean_text(self.heading)


# ================= EPUB =================


def _safe_member_name(name: str) -> str:
    """条目名归一化并拒绝路径穿越写法（只读路径也必须校验）"""
    norm = name.replace("\\", "/")
    if norm.startswith("/") or any(part == ".." for part in norm.split("/")):
        raise ParseError("EPUB 包含非法路径，已拒绝解析")
    return norm


def _read_capped(zf: zipfile.ZipFile, name: str, cap: int, total: list[int]) -> bytes:
    """流式读取 zip 条目，超过单条目或总预算立即失败（防 ZIP Bomb）"""
    try:
        info = zf.getinfo(name)
    except KeyError as exc:
        raise ParseError(f"EPUB 缺少必要文件：{name}") from exc
    if info.file_size > cap:
        raise ParseError("EPUB 内文件过大，已拒绝解析")
    total[0] += info.file_size
    if total[0] > EPUB_MAX_TOTAL_BYTES:
        raise ParseError("EPUB 解压总大小超出限制，已拒绝解析")
    chunks: list[bytes] = []
    read = 0
    with zf.open(name) as fh:
        while True:
            buf = fh.read(1024 * 256)
            if not buf:
                break
            read += len(buf)
            if read > cap:  # 声明大小与实际不符（伪造 central directory）也拦截
                raise ParseError("EPUB 内文件解压后超出限制，已拒绝解析")
            chunks.append(buf)
    return b"".join(chunks)


def _xml_root(data: bytes, what: str) -> ET.Element:
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise ParseError(f"EPUB 的 {what} 不是合法 XML") from exc


def _epub_metadata(opf: ET.Element) -> dict[str, str]:
    """读取 Dublin Core 元数据（标题/作者/语言）"""
    dc = "{http://purl.org/dc/elements/1.1/}"
    out: dict[str, str] = {}
    for key in ("title", "creator", "language"):
        node = opf.find(f".//{dc}{key}")
        if node is not None and node.text and node.text.strip():
            out[key] = node.text.strip()
    return out


def parse_epub(data: bytes, fallback_title: str) -> ParsedBook:
    """解析 EPUB：container.xml → OPF(manifest/spine) → 按 spine 顺序提取正文"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ParseError("EPUB 文件已损坏或不是合法的 ZIP 包") from exc

    with zf:
        infos = zf.infolist()
        if len(infos) > EPUB_MAX_ENTRIES:
            raise ParseError(f"EPUB 内文件数量过多（{len(infos)} > {EPUB_MAX_ENTRIES}），已拒绝解析")
        declared_total = sum(i.file_size for i in infos)
        if declared_total > EPUB_MAX_TOTAL_BYTES:
            raise ParseError("EPUB 解压总大小超出限制，已拒绝解析")
        if any(i.file_size > EPUB_MAX_ENTRY_BYTES for i in infos):
            raise ParseError("EPUB 内单个文件过大，已拒绝解析")

        names = {_safe_member_name(i.filename) for i in infos}
        if "META-INF/container.xml" not in names:
            raise ParseError("不是有效的 EPUB：缺少 META-INF/container.xml")

        total = [0]
        container = _xml_root(
            _read_capped(zf, "META-INF/container.xml", XML_MAX_BYTES, total), "container.xml"
        )
        # container.xml 的命名空间在不同生成器下可能缺失，按 full-path 属性查找最稳
        rootfiles = [e for e in container.iter() if e.get("full-path")]
        if not rootfiles:
            raise ParseError("不是有效的 EPUB：container.xml 中缺少 rootfile 声明")
        opf_path = _safe_member_name(unquote(rootfiles[0].get("full-path") or ""))
        if not opf_path or opf_path not in names:
            raise ParseError("不是有效的 EPUB：找不到内容清单（OPF）")

        opf = _xml_root(_read_capped(zf, opf_path, XML_MAX_BYTES, total), "OPF")
        meta = _epub_metadata(opf)

        opf_ns = "{http://www.idpf.org/2007/opf}"
        manifest: dict[str, tuple[str, str]] = {}
        for item in opf.findall(f".//{opf_ns}item"):
            item_id, href = item.get("id"), item.get("href")
            if item_id and href:
                manifest[item_id] = (unquote(href), (item.get("media-type") or "").lower())

        chapter_docs: list[str] = []
        for ref in opf.findall(f".//{opf_ns}itemref"):
            idref = ref.get("idref")
            if not idref or idref not in manifest:
                continue
            href, media = manifest[idref]
            if not (media.endswith("html") or media.endswith("xml") or media == ""):
                continue  # 跳过图片/字体等非正文资源（不加载外部资源）
            doc_path = _safe_member_name(
                posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), href))
            )
            if doc_path in names:
                chapter_docs.append(doc_path)

        chapters: list[tuple[str, str]] = []
        for idx, doc_path in enumerate(chapter_docs, start=1):
            raw = _read_capped(zf, doc_path, EPUB_MAX_ENTRY_BYTES, total)
            parser = _TextExtractor()
            parser.feed(raw.decode("utf-8", errors="replace"))
            body = parser.text()
            if not body:
                continue
            title = parser.heading_text() or f"Chapter {idx}"
            chapters.append((title[:255], body))

    if not chapters:
        raise ParseError("未能从 EPUB 中提取到正文（可能为空文件或仅含图片）")

    # 单个文档装整本书时（无分节标记），回退到通用章节切分规则
    if len(chapters) == 1:
        total_words = word_count(chapters[0][1])
        if total_words > 4000:
            split = split_chapters(chapters[0][1])
            if len(split) > 1:
                chapters = [
                    (t or f"Chapter {i}", b) for i, (t, b) in enumerate(split, start=1)
                ]

    return ParsedBook(
        title=meta.get("title") or fallback_title,
        author=meta.get("creator") or "未知作者",
        language=(meta.get("language") or "en")[:16],
        source_type="epub",
        chapters=chapters,
    )


# ================= TXT =================


def parse_txt(data: bytes, fallback_title: str) -> ParsedBook:
    """解析 TXT：编码兜底解码 → 复用项目章节切分规则"""
    text = _clean_text(_decode_text(data))
    if word_count(text) < 10:
        raise ParseError("文本内容为空或过短，无法作为书籍解析")

    split = split_chapters(text)
    if len(split) <= 1:
        chapters = [("Full Text", text)]
    else:
        chapters = [(t or f"Chapter {i}", b) for i, (t, b) in enumerate(split, start=1)]

    return ParsedBook(
        title=fallback_title,
        author="未知作者",
        language="en",
        source_type="txt",
        chapters=chapters,
    )


# ================= 入口 =================


def parse_upload(filename: str, data: bytes) -> ParsedBook:
    """上传解析入口：真实类型判定 → 分派解析器"""
    _, actual = detect_type(filename, data)
    fallback = _fallback_title(filename)
    book = parse_epub(data, fallback) if actual == "epub" else parse_txt(data, fallback)
    # 统一收尾校验：章节顺序连续、正文非空
    for i, (_, body) in enumerate(book.chapters, start=1):
        if not body.strip():
            raise ParseError(f"第 {i} 章正文为空，解析失败")
    if len(book.chapters) > 1000:
        raise ParseError("章节数量超出限制（>1000），已拒绝解析")
    return book
