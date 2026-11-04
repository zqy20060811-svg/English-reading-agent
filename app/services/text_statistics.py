"""个人书籍分析的基础文本统计：纯本地 Python 计算，不调用 LLM。

覆盖需求：
- 全书/章节词数、不重复词汇数、词汇频率分布
- 平均句长、长句比例（>25 词视为长句）
- CEFR 词汇等级分布（cefr_lexicon，查不到记 unknown）
- 语法特征本地规则初筛（从句/被动/虚拟/非谓语等粗粒度计数 + 例句采样）

CPU 密集：调用方必须放入线程池（asyncio.to_thread / run_in_threadpool）执行。
规则为启发式，识别结果仅作 LLM 分析的输入线索，不作为最终结论。
"""

import re
from collections import Counter

from app.services.cefr_lexicon import LEVELS, classify_tokens, load_lexicon, normalize_token

# 长句阈值（词数）：超过视为长难句候选
LONG_SENTENCE_WORDS = 25
# 例句采样：每个语法特征最多保留的例句数
MAX_EXAMPLES_PER_FEATURE = 1
# 词频明细：只保留 top N 高频词与 top N 未知词，避免 JSONB 膨胀
TOP_FREQ_WORDS = 30
TOP_UNKNOWN_WORDS = 30

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")

# 句子切分：句号/问号/叹号后跟空白或结尾；省略号与缩写（Mr. 等）存在误切，
# 属于启发式统计可接受误差（统一口径用于句长计算即可）
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
# 常见缩写不作为句子结束（简单后向排除）
_ABBREV_RE = re.compile(r"\b(Mr|Mrs|Ms|Dr|St|vs|etc|Fig|No)\.$")

_SENTENCE_MAX_CHARS = 400  # 例句采样单句长度上限

# ---- 语法特征启发式规则 ----
_GRAMMAR_RULES: dict[str, str] = {
    # 被动语态：be + 过去分词（粗匹配 -ed，允许不规则分词常见形式）
    "passive_voice": (
        r"\b(?:is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?"
        r"(?:\w+ed|done|given|taken|made|found|held|kept|told|shown|sent|built|brought|known|thought)\b"
    ),
    # 定语从句：关系代词 which/who/whom/whose/that 引导（that 同时可指状语，粗粒度可接受）
    "relative_clause": r"\b(?:which|whom|whose)\b|\bthat\b\s+(?:\w+\s+){0,2}\b(?:is|was|are|were|has|had|will|can)\b",
    # 名词性从句：that/whether/if/what 引导的宾语从句常见形式
    "noun_clause": r"\b(?:\w+\s+)?(?:said|thought|knew|felt|believed|realized|remembered|wondered|asked)\s+(?:that|whether|if|what|why|how)\b",
    # 状语从句：从属连词
    "adverbial_clause": r"\b(?:when|while|although|though|because|since|unless|until|whereas|before|after|as soon as)\b",
    # 条件与虚拟：would/could/might + 动词原形，以及 if 条件句
    "conditional_mood": r"\b(?:would|could|might)\s+(?:\w+\s+)?(?:\w+(?:ly))?\b(?:\w+)?\s*\w*(?:ed|en)?\b|\bif\b",
    # 非谓语：句中 -ing/-ed 分词短语（逗号后开头）与不定式 to do
    "nonfinite_verb": r"(?:,\s*(?:\w+ing|\w+ed))|\bto\s+(?:\w+(?:ly))?\b",
    # 完成时：have/has/had + 分词
    "perfect_tense": r"\b(?:have|has|had)\s+(?:\w+ly\s+)?(?:\w+ed|done|given|taken|made|gone|seen|been|known|thought|found|held|kept|told|shown|sent)\b",
    # 倒装/强调：句首否定或限制副词（句子级检测见 _inversion_count）
    "inversion_front": r"^(?:Never|Not\s+only|Only\s+(?:then|when|now|after|in|by|with)|Hardly|Scarcely|No\s+sooner|Seldom|Little)\b",
}


def tokenize(text: str) -> list[str]:
    """切出英文词 token（与 personal_parser.word_count 同一口径）"""
    return _TOKEN_RE.findall(text)


def split_sentences(text: str) -> list[str]:
    """粗粒度句子切分：按 .!? 分隔，过滤空句与缩写误切产生的碎片"""
    sentences = []
    for part in _SENT_SPLIT_RE.split(text):
        part = part.strip()
        if not part:
            continue
        if sentences and _ABBREV_RE.search(sentences[-1][-6:] if len(sentences[-1]) >= 6 else sentences[-1]):
            sentences[-1] += " " + part
            continue
        sentences.append(part)
    return sentences


def sentence_stats(text: str) -> tuple[float, float, list[str]]:
    """平均句长、长句比例、句子列表。空文本返回 (0, 0, [])。"""
    sentences = split_sentences(text)
    if not sentences:
        return 0.0, 0.0, []
    lengths = [len(tokenize(s)) for s in sentences]
    avg = sum(lengths) / len(lengths)
    long_ratio = sum(1 for n in lengths if n > LONG_SENTENCE_WORDS) / len(lengths)
    return round(avg, 1), round(long_ratio, 4), sentences


def vocabulary_statistics(text: str, tokens: list[str]) -> dict:
    """词汇频率分布与难度概况（明细裁剪到 top N，避免结果表膨胀）。

    - top_freq_words：最高频实义词（排除超高频功能词之外的都保留，由读者自行判断）
    - unknown_words：词典未收录的词按频次取样（可能是专有名词/专业词/生僻词，
      并不等于难词，仅作为 LLM 分析线索）
    """
    counts = Counter(normalize_token(t) for t in tokens)
    top_freq = [
        {"word": w, "count": c}
        for w, c in counts.most_common(TOP_FREQ_WORDS)
    ]
    lexicon = load_lexicon()
    unknown = [
        {"word": w, "count": c}
        for w, c in counts.items()
        if c >= 2 and w not in lexicon
    ]
    unknown.sort(key=lambda x: -x["count"])
    return {
        "unique_word_count": len(counts),
        "top_freq_words": top_freq,
        "unknown_words": unknown[:TOP_UNKNOWN_WORDS],
    }


def grammar_features(text: str, sentences: list[str]) -> dict:
    """语法特征本地规则初筛：每类计数 + 例句采样。

    全部为启发式正则，计数口径粗粒度（可能多计/漏计），
    用途是把 LLM 注意力引到确实出现复杂句式的章节。
    """
    features: dict[str, dict] = {}
    for name, pattern in _GRAMMAR_RULES.items():
        if name == "inversion_front":
            count, examples = _inversion_count(sentences)
        else:
            compiled = re.compile(pattern, re.IGNORECASE)
            count = 0
            examples = []
            for s in sentences:
                if len(s) > _SENTENCE_MAX_CHARS:
                    continue
                m = compiled.search(s)
                if m:
                    count += 1
                    if len(examples) < MAX_EXAMPLES_PER_FEATURE:
                        examples.append(s.strip())
        features[name] = {"count": count, "examples": examples}
    return features


def _inversion_count(sentences: list[str]) -> tuple[int, list[str]]:
    """倒装/强调句：句首否定或限制副词（仅句首匹配，误报率低）"""
    compiled = re.compile(_GRAMMAR_RULES["inversion_front"], re.IGNORECASE)
    count = 0
    examples: list[str] = []
    for s in sentences:
        if len(s) > _SENTENCE_MAX_CHARS:
            continue
        if compiled.match(s.strip()):
            count += 1
            if len(examples) < MAX_EXAMPLES_PER_FEATURE:
                examples.append(s.strip())
    return count, examples


def analyze_chapter_text(text: str) -> dict:
    """单章本地统计汇总（一次算齐，供落库与 LLM prompt 使用）"""
    tokens = tokenize(text)
    avg_len, long_ratio, sentences = sentence_stats(text)
    levels = classify_tokens(tokens)
    stats = vocabulary_statistics(text, tokens)
    total = len(tokens)
    return {
        "word_count": total,
        "unique_word_count": stats["unique_word_count"],
        "average_sentence_length": avg_len,
        "long_sentence_ratio": long_ratio,
        "vocabulary_level_distribution": levels,
        "vocabulary_statistics": stats,
        "grammar_features": grammar_features(text, sentences),
    }


def aggregate_book_stats(chapter_stats: list[dict]) -> dict:
    """汇总各章统计为全书口径（本地计算，不调 LLM）"""
    total_words = sum(c["word_count"] for c in chapter_stats)
    total_tokens_per_level = {lv: 0 for lv in LEVELS}
    total_tokens_per_level["unknown"] = 0
    grammar_totals: Counter = Counter()
    weighted_len = 0.0
    weighted_long = 0.0
    for c in chapter_stats:
        for lv, n in c["vocabulary_level_distribution"].items():
            total_tokens_per_level[lv] = total_tokens_per_level.get(lv, 0) + n
        # 兼容两种结构：本地规则直接存特征 / 落库后嵌套在 local_rules 下
        rules = c["grammar_features"].get("local_rules", c["grammar_features"])
        for name, data in rules.items():
            grammar_totals[name] += data.get("count", 0)
        n = c["word_count"]
        weighted_len += c["average_sentence_length"] * n
        weighted_long += c["long_sentence_ratio"] * n
    if total_words > 0:
        avg_len = round(weighted_len / total_words, 1)
        long_ratio = round(weighted_long / total_words, 4)
    else:
        avg_len, long_ratio = 0.0, 0.0
    return {
        "total_word_count": total_words,
        "average_sentence_length": avg_len,
        "long_sentence_ratio": long_ratio,
        "vocabulary_level_distribution": total_tokens_per_level,
        "main_grammar_features": {
            name: {"count": count}
            for name, count in grammar_totals.most_common()
        },
    }
