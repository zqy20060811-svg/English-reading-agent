"""检索评测基准数据集（25 题）。

每条记录：
- question: 用户问题（覆盖中文跨语言 / 英文原文定位 / 人物关系 / 词汇 / 书中无答案五类）
- book_id: 检索范围（对齐 /ask/reading 部署配置：固定书内检索）；None 表示全局（无答案题仅用于拒答观察）
- expected_chapter_indexes: 标准证据所在章节（book_chapters.chapter_index）
- should_answer: 是否应有证据可命中（False = 书中无答案，应拒答）

标注依据：人工通读各书章节标题与原文抽查确认；改动分块/向量模型后需重跑 test_retrieval 复核。
"""

from dataclasses import dataclass, field


@dataclass
class RetrievalCase:
    id: str
    question: str
    book_id: int | None
    expected_chapter_indexes: list[int] = field(default_factory=list)
    should_answer: bool = True
    category: str = ""  # 中文跨语言 / 英文定位 / 人物关系 / 词汇 / 无答案


BOOK_ALICE = 2
BOOK_CAROL = 1
BOOK_MOBY = 5
BOOK_PAN = 6
BOOK_OZ = 14
BOOK_ISLAND = 15
BOOK_FRANKENSTEIN = 4

BENCHMARK_CASES: list[RetrievalCase] = [
    # --- 中文提问（跨语言） ---
    RetrievalCase("q1",  "爱丽丝掉进了什么洞？", BOOK_ALICE, [1], category="中文跨语言"),
    RetrievalCase("q2",  "三月兔和帽匠为什么觉得时间是停着的？", BOOK_ALICE, [7], category="中文跨语言"),
    RetrievalCase("q3",  "红心王后下令砍掉所有人的头发生在哪场球赛上？", BOOK_ALICE, [8], category="中文跨语言"),
    RetrievalCase("q4",  "斯克鲁奇的外甥是怎么劝他的？", BOOK_CAROL, [1, 3], category="中文跨语言"),
    RetrievalCase("q5",  "小气鬼蒂姆一家靠什么生活？", BOOK_CAROL, [3, 4], category="中文跨语言"),
    RetrievalCase("q7",  "弗兰肯斯坦用人体拼出了什么？", BOOK_FRANKENSTEIN, [5], category="中文跨语言"),
    RetrievalCase("q8",  "白鲸船长为什么疯狂追捕白鲸？", BOOK_MOBY, [36, 41], category="中文跨语言"),
    RetrievalCase("q9",  "彼得潘是怎么飞进卧室的？", BOOK_PAN, [2, 3], category="中文跨语言"),
    RetrievalCase("q10", "绿野仙踪的多萝西被龙卷风吹到了哪里？", BOOK_OZ, [1, 2], category="中文跨语言"),
    # --- 英文原文定位 ---
    RetrievalCase("q11", "Why does Scrooge hate Christmas?", BOOK_CAROL, [1], category="英文定位"),
    RetrievalCase("q12", "Where does Alice fall down and what is at the bottom?", BOOK_ALICE, [1, 2], category="英文定位"),
    RetrievalCase("q13", "How did the White Rabbit lose his gloves and fan?", BOOK_ALICE, [4], category="英文定位"),
    RetrievalCase("q14", "What bargain does the Cheshire Cat offer about directions?", BOOK_ALICE, [6], category="英文定位"),
    RetrievalCase("q15", "Who is accused of stealing the tarts?", BOOK_ALICE, [11, 12], category="英文定位"),
    RetrievalCase("q16", "What does the Ghost of Christmas Present show Scrooge?", BOOK_CAROL, [3], category="英文定位"),
    RetrievalCase("q17", "What warning does Marley's ghost give Scrooge?", BOOK_CAROL, [2], category="英文定位"),
    # --- 人物关系 ---
    RetrievalCase("q18", "谁是爱丽丝在审判中遇到的三位牌园丁？", BOOK_ALICE, [8, 11], category="人物关系"),
    RetrievalCase("q19", "What relation is Scrooge to Fred?", BOOK_CAROL, [1, 3, 5], category="人物关系"),
    RetrievalCase("q20", "Who adopts the narrator in Treasure Island and who hides in the apple barrel?", BOOK_ISLAND, [1, 7], category="人物关系"),
    # --- 词汇/专名 ---
    RetrievalCase("q21", "' Ebenezer' 这个名字在书里指谁？", BOOK_CAROL, [1], category="词汇专名"),
    RetrievalCase("q22", "What does 'curiouser' mean in Alice's words?", BOOK_ALICE, [2, 4], category="词汇专名"),
    # --- 书中无答案（应拒答） ---
    RetrievalCase("q23", "鲁迅的原名是什么？", BOOK_ALICE, [], False, "无答案"),
    RetrievalCase("q24", "What is the capital of France?", BOOK_ALICE, [], False, "无答案"),
    RetrievalCase("q25", "How do I bake a chocolate cake at home?", BOOK_ALICE, [], False, "无答案"),
]
