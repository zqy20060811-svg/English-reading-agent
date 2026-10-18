"""预设英语水平测试题库（静态，可控评分标准；后续可扩展 LLM 动态出题）。

- 4 个等级（CEFR：A2/B1/B2/C1）× 3 个维度（词汇/语法/阅读）× 各 2 题 = 24 题
- 答案与解析仅存于服务端，接口下发的题目不含 answer/explanation
- 评分权重随等级递增：A2=1 分、B1=2 分、B2=3 分、C1=4 分（满分 60）
"""

from dataclasses import dataclass

LEVELS = ["A2", "B1", "B2", "C1"]  # 等级由低到高
DIMENSIONS = ["vocabulary", "grammar", "reading"]  # 词汇 / 语法 / 阅读理解
LEVEL_SCORE = {"A2": 1, "B1": 2, "B2": 3, "C1": 4}  # 每题分值


@dataclass(frozen=True)
class LevelQuestion:
    id: str
    level: str       # CEFR 等级
    dimension: str   # vocabulary / grammar / reading
    text: str        # 题干（阅读题含短文）
    options: list[str]
    answer_index: int
    explanation: str


LEVEL_BANK: list[LevelQuestion] = [
    # ---------- A2 词汇 ----------
    LevelQuestion("v-a2-1", "A2", "vocabulary",
                  "Choose the word that means the opposite of \"big\".",
                  ["small", "tall", "long", "old"], 0, "big 的反义词是 small。"),
    LevelQuestion("v-a2-2", "A2", "vocabulary",
                  "She drinks ______ every morning.",
                  ["coffee", "carpet", "garden", "pencil"], 0, "喝的对象应为 coffee。"),
    # ---------- A2 语法 ----------
    LevelQuestion("g-a2-1", "A2", "grammar",
                  "He ______ to school every day.",
                  ["goes", "go", "going", "gone"], 0, "第三人称单数一般现在时用 goes。"),
    LevelQuestion("g-a2-2", "A2", "grammar",
                  "______ you like some tea?",
                  ["Would", "Are", "Is", "Have"], 0, "礼貌请求用 Would you like...。"),
    # ---------- A2 阅读 ----------
    LevelQuestion("r-a2-1", "A2", "reading",
                  "Tom gets up at seven o'clock. He has breakfast with his sister, "
                  "and then he walks to school. School starts at eight.\n\n"
                  "How does Tom go to school?",
                  ["He walks.", "He takes a bus.", "He rides a bike.", "He drives a car."],
                  0, "原文 he walks to school。"),
    LevelQuestion("r-a2-2", "A2", "reading",
                  "Mary has a little dog. The dog is white and very friendly. "
                  "It likes to play with a red ball in the garden.\n\n"
                  "What color is Mary's dog?",
                  ["White.", "Black.", "Brown.", "Red."], 0, "原文 The dog is white。"),
    # ---------- B1 词汇 ----------
    LevelQuestion("v-b1-1", "B1", "vocabulary",
                  "Choose the word closest in meaning to \"brave\".",
                  ["courageous", "careful", "clever", "calm"], 0, "brave = courageous。"),
    LevelQuestion("v-b1-2", "B1", "vocabulary",
                  "The meeting was ______ until next Monday because the manager was ill.",
                  ["postponed", "predicted", "performed", "preferred"], 0,
                  "推迟会议用 postponed。"),
    # ---------- B1 语法 ----------
    LevelQuestion("g-b1-1", "B1", "grammar",
                  "I ______ TV when the phone rang.",
                  ["was watching", "watched", "am watching", "have watched"], 0,
                  "过去进行时描述被打断的持续动作。"),
    LevelQuestion("g-b1-2", "B1", "grammar",
                  "She has lived in London ______ 2015.",
                  ["since", "for", "from", "at"], 0, "since + 时间点，for + 时间段。"),
    # ---------- B1 阅读 ----------
    LevelQuestion("r-b1-1", "B1", "reading",
                  "When Ben missed the last bus, he decided to walk home through the park. "
                  "It was a cold night, but he knew a shortcut. Halfway across, he saw "
                  "an old man feeding the birds, even though it was almost midnight.\n\n"
                  "What was unusual about what Ben saw?",
                  ["Someone was feeding birds at midnight.",
                   "The park was closed for repairs.",
                   "The old man was lost in the park.",
                   "There were no birds in the park."],
                  0, "深夜喂鸟是反常之处。"),
    LevelQuestion("r-b1-2", "B1", "reading",
                  "Anna wanted to buy her mother a scarf for her birthday, but she had "
                  "only saved half the money. Instead of asking her father, she spent "
                  "her weekends helping a neighbor with shopping and finally bought "
                  "the scarf with her own earnings.\n\n"
                  "What does this story mainly show about Anna?",
                  ["She is independent and hard-working.",
                   "She dislikes asking for help.",
                   "She is careless with money.",
                   "She prefers scarves to other gifts."],
                  0, "主旨：自食其力、独立勤快。"),
    # ---------- B2 词汇 ----------
    LevelQuestion("v-b2-1", "B2", "vocabulary",
                  "The scientist's claims were ______; nobody could find any flaw in her reasoning.",
                  ["flawless", "fruitless", "frequent", "fragile"], 0,
                  "无懈可击 = flawless。"),
    LevelQuestion("v-b2-2", "B2", "vocabulary",
                  "His explanation sounded plausible, but the evidence told a different story.",
                  ["believable", "generous", "detailed", "confusing"], 0,
                  "plausible = seemingly believable。"),
    # ---------- B2 语法 ----------
    LevelQuestion("g-b2-1", "B2", "grammar",
                  "If she ______ the early train, she wouldn't have missed the interview.",
                  ["had caught", "caught", "would catch", "has caught"], 0,
                  "第三条件句：had + 过去分词。"),
    LevelQuestion("g-b2-2", "B2", "grammar",
                  "Not only ______ the exam, but he also got the highest score in his class.",
                  ["did he pass", "he passed", "passed he", "he did pass"], 0,
                  "Not only 置于句首需部分倒装：did he pass。"),
    # ---------- B2 阅读 ----------
    LevelQuestion("r-b2-1", "B2", "reading",
                  "For years, the town had priced its water by a flat monthly fee, so heavy "
                  "users paid no more than careful ones. When the council switched to "
                  "metered billing, consumption fell by a quarter within a year — not "
                  "because anyone had preached conservation, but because the price "
                  "signal finally did the work.\n\n"
                  "What is the main idea of the passage?",
                  ["Pricing can change behavior more effectively than persuasion.",
                   "The council wanted people to use more water.",
                   "Flat fees encouraged careful use of water.",
                   "Water consumption rose after metered billing."],
                  0, "主旨：价格机制比说教更能改变行为。"),
    LevelQuestion("r-b2-2", "B2", "reading",
                  "The review praised the novel's dialogue as \"deceptively simple\": every "
                  "character seems to speak in ordinary sentences, yet each speech quietly "
                  "betrays motives the speaker would never admit aloud.\n\n"
                  "What does \"deceptively simple\" suggest about the dialogue?",
                  ["It looks plain but carries hidden depth.",
                   "It is simple and also dishonest.",
                   "It is complicated and hard to follow.",
                   "It misquotes the characters on purpose."],
                  0, "deceptively simple = 看似简单实则暗藏深意。"),
    # ---------- C1 词汇 ----------
    LevelQuestion("v-c1-1", "C1", "vocabulary",
                  "The minister's statement was deliberately ______, designed to reassure "
                  "both sides without committing to either.",
                  ["ambiguous", "articulate", "audacious", "adamant"], 0,
                  "模棱两可 = ambiguous。"),
    LevelQuestion("v-c1-2", "C1", "vocabulary",
                  "Rather than confronting the crisis head-on, the board chose to ______ "
                  "it, postponing any real decision indefinitely.",
                  ["sidestep", "scrutinize", "substantiate", "salvage"], 0,
                  "回避问题 = sidestep。"),
    # ---------- C1 语法 ----------
    LevelQuestion("g-c1-1", "C1", "grammar",
                  "______ had the expedition set out than the storms forced it back to base.",
                  ["No sooner", "Hardly when", "Scarcely than", "Not until"], 0,
                  "No sooner ... than 固定搭配且引起倒装。"),
    LevelQuestion("g-c1-2", "C1", "grammar",
                  "The committee insisted that the report ______ revised before publication.",
                  ["be", "is", "was", "would be"], 0,
                  "insist that + 虚拟语气 (should) be。"),
    # ---------- C1 阅读 ----------
    LevelQuestion("r-c1-1", "C1", "reading",
                  "It is tempting to see the author's late style as mere decay: the sentences "
                  "grow shorter, the ironies flatter. Yet this reading mistakes compression "
                  "for exhaustion. What reads at first as fatigue is better understood as a "
                  "deliberate refusal of ornament — a style that trusts the reader to hear "
                  "what is no longer said.\n\n"
                  "The author argues that the late style should be read as:",
                  ["a deliberate minimalism, not a decline",
                   "an accidental collapse of skill",
                   "an imitation of earlier fashions",
                   "a challenge to the publisher's taste"],
                  0, "主旨：晚期文风是刻意的克制而非衰退。"),
    LevelQuestion("r-c1-2", "C1", "reading",
                  "The experiment's success owed less to the elegance of its design than to "
                  "the stubbornness of its designer: had the first three failures been taken "
                  "at face value, as the reviewers urged, the anomalous reading that led to "
                  "the discovery would never have been chased down.\n\n"
                  "What made the discovery possible?",
                  ["Persistence despite apparently decisive failures",
                   "A flawless experimental design",
                   "The reviewers' early intervention",
                   "Abandoning anomalous readings quickly"],
                  0, "主旨：对失败不轻信、坚持追查才带来发现。"),
]


def questions_by_id() -> dict[str, LevelQuestion]:
    return {q.id: q for q in LEVEL_BANK}
