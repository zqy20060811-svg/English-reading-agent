"""书单目录：全部选自 Project Gutenberg 的公有领域英文书，纯文本格式公开可爬。"""

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class BookMeta:
    """一本书的基础元数据。"""

    gutenberg_id: int   # Project Gutenberg 电子书编号
    title: str          # 书名
    author: str         # 作者
    year: int           # 首次出版年份
    genre: str          # 题材分类
    synopsis: str       # 英文内容简介（入库时存入 PostgreSQL，正文不存库）


# 共 20 本经典英文书，可通过 --limit 控制实际抓取数量（10~20）
BOOK_CATALOG: list[BookMeta] = [
    BookMeta(
        1342, "Pride and Prejudice", "Jane Austen", 1813, "Romance",
        "The spirited Elizabeth Bennet clashes with the proud, wealthy Mr. Darcy in "
        "this witty comedy of manners about love, pride and social class in "
        "regency-era rural England.",
    ),
    BookMeta(
        11, "Alice's Adventures in Wonderland", "Lewis Carroll", 1865, "Fantasy",
        "Young Alice falls down a rabbit hole into a absurd wonderland of talking "
        "animals, a grinning Cheshire Cat and a tea party hosted by the Mad Hatter, "
        "where logic is turned delightfully upside down.",
    ),
    BookMeta(
        1661, "The Adventures of Sherlock Holmes", "Arthur Conan Doyle", 1892, "Detective",
        "Twelve classic cases solved by the brilliant detective Sherlock Holmes and "
        "his loyal companion Dr. Watson, from stolen jewels to mysterious deaths, "
        "all narrated with razor-sharp deduction.",
    ),
    BookMeta(
        46, "A Christmas Carol", "Charles Dickens", 1843, "Fiction",
        "The miserly Ebenezer Scrooge is visited by three spirits on Christmas Eve "
        "who show him his past, present and future, transforming him from a "
        "cold-hearted miser into a generous man.",
    ),
    BookMeta(
        84, "Frankenstein", "Mary Shelley", 1818, "Science Fiction",
        "Obsessed scientist Victor Frankenstein creates a living creature from dead "
        "matter, then abandons it. His rejected creation seeks revenge in this "
        "gothic tale of ambition and responsibility.",
    ),
    BookMeta(
        174, "The Picture of Dorian Gray", "Oscar Wilde", 1890, "Gothic",
        "Dorian Gray wishes his portrait would age instead of him. As he descends "
        "into vice, the painting grows hideously ugly while he remains forever "
        "young in this philosophical gothic novel.",
    ),
    BookMeta(
        345, "Dracula", "Bram Stoker", 1897, "Gothic",
        "Count Dracula moves from Transylvania to England, spreading vampirism and "
        "preying on young Lucy and Mina, until a small band led by Professor Van "
        "Helsing hunts him down.",
    ),
    BookMeta(
        35, "The Time Machine", "H. G. Wells", 1895, "Science Fiction",
        "A Victorian inventor travels hundreds of thousands of years into the "
        "future and discovers humanity split into the fragile Eloi and the brutal "
        "underground Morlocks.",
    ),
    BookMeta(
        36, "The War of the Worlds", "H. G. Wells", 1898, "Science Fiction",
        "Martians land in Surrey, England, and begin a devastating invasion with "
        "heat-rays and tripods, told through the eyes of an unnamed narrator "
        "struggling to survive.",
    ),
    BookMeta(
        2701, "Moby Dick", "Herman Melville", 1851, "Adventure",
        "Sailor Ishmael joins the whaling ship Pequod under the monomaniacal "
        "Captain Ahab, who is obsessed with hunting the great white whale Moby "
        "Dick that took his leg.",
    ),
    BookMeta(
        120, "Treasure Island", "Robert Louis Stevenson", 1883, "Adventure",
        "Young Jim Hawkins finds a treasure map and sails with the crew of the "
        "Hispaniola, only to discover that the charming ship's cook Long John "
        "Silver leads a band of mutinous pirates.",
    ),
    BookMeta(
        74, "The Adventures of Tom Sawyer", "Mark Twain", 1876, "Adventure",
        "Mischievous Tom Sawyer tricks his friends into whitewashing a fence, "
        "witnesses a murder in a graveyard and gets lost in a cave with his "
        "sweetheart Becky Thatcher along the Mississippi River.",
    ),
    BookMeta(
        55, "The Wonderful Wizard of Oz", "L. Frank Baum", 1900, "Fantasy",
        "Carried away by a cyclone, Dorothy and her dog Toto land in the magical "
        "Land of Oz and follow the Yellow Brick Road with a scarecrow, a tin "
        "woodman and a cowardly lion to find the Wizard.",
    ),
    BookMeta(
        16, "Peter Pan", "J. M. Barrie", 1911, "Fantasy",
        "The boy who never grows up whisks Wendy, John and Michael Darling away "
        "to Neverland, a world of fairies, pirates, mermaids and the dreaded "
        "Captain Hook.",
    ),
    BookMeta(
        215, "The Call of the Wild", "Jack London", 1903, "Adventure",
        "Buck, a pampered St. Bernard mix, is stolen and sold as a sled dog in the "
        "frozen Yukon during the gold rush, gradually answering the primal call of "
        "the wild.",
    ),
    BookMeta(
        45, "Anne of Green Gables", "L. M. Montgomery", 1908, "Fiction",
        "Talkative, red-headed orphan Anne Shirley is mistakenly sent to live with "
        "an elderly brother and sister on Prince Edward Island, where her "
        "imagination and charm win over the whole village.",
    ),
    BookMeta(
        514, "Little Women", "Louisa May Alcott", 1868, "Fiction",
        "The four March sisters - Meg, Jo, Beth and Amy - grow up in Civil War-era "
        "New England, navigating poverty, love, loss and their dreams in this "
        "beloved coming-of-age story.",
    ),
    BookMeta(
        113, "The Secret Garden", "Frances Hodgson Burnett", 1911, "Fiction",
        "Orphaned Mary Lennox, sent to a lonely Yorkshire mansion, discovers a "
        "locked garden and, with her cousin Colin, brings it back to life as the "
        "children themselves are healed.",
    ),
    BookMeta(
        98, "A Tale of Two Cities", "Charles Dickens", 1859, "Historical",
        "Set in London and Paris during the French Revolution, this novel follows "
        " Lawyer Sydney Carton and aristocrat Charles Darnay toward a supreme act "
        "of sacrifice amid revolutionary terror.",
    ),
    BookMeta(
        64317, "The Great Gatsby", "F. Scott Fitzgerald", 1925, "Fiction",
        "Mysterious millionaire Jay Gatsby throws lavish parties on Long Island "
        "hoping to rekindle his lost love Daisy Buchanan in this glittering, "
        "tragic portrait of the Jazz Age.",
    ),
]

# Gutenberg 纯文本下载地址模板（UTF-8 统一编码）
TXT_URL_TEMPLATE = "https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt"


def book_to_dict(book: BookMeta) -> dict:
    """转为可序列化的字典。"""
    return asdict(book)
