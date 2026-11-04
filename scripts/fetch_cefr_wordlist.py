"""下载 CEFR 词汇等级词典到 data/cefr/（该目录已在 .gitignore，不随仓库分发）。

数据来源与许可：
1. CEFR-J Vocabulary Profile 1.5（A1~B2，约 7,000 词条）
   - 作者：Tono, Yukio（东京外国语大学 Tono Laboratory）
   - 许可：研究与商业用途免费，使用时须引用数据集：
     Tono, Yukio. The CEFR-J Wordlist Version 1.5. Tokyo University of Foreign Studies. http://www.cefr-j.org/
2. Octanove Vocabulary Profile C1/C2 1.0（C1/C2 补充，约 1,700 词条）
   - 作者：Octanove Labs
   - 许可：CC BY-SA 4.0（https://creativecommons.org/licenses/by-sa/4.0/）

运行：python scripts/fetch_cefr_wordlist.py
"""

import sys
from pathlib import Path

import urllib.request

DATA_DIR = Path("data/cefr")
FILES = {
    "cefrj-vocabulary-profile-1.5.csv":
        "https://raw.githubusercontent.com/openlanguageprofiles/olp-en-cefrj/master/cefrj-vocabulary-profile-1.5.csv",
    "octanove-vocabulary-profile-c1c2-1.0.csv":
        "https://raw.githubusercontent.com/openlanguageprofiles/olp-en-cefrj/master/octanove-vocabulary-profile-c1c2-1.0.csv",
}


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    failed = []
    for filename, url in FILES.items():
        target = DATA_DIR / filename
        if target.is_file() and target.stat().st_size > 0:
            print(f"[skip] {filename} 已存在")
            continue
        try:
            print(f"[down] {url}")
            with urllib.request.urlopen(url, timeout=30) as resp:
                target.write_bytes(resp.read())
            print(f"[ok]   {filename}（{target.stat().st_size} 字节）")
        except Exception as exc:
            failed.append(filename)
            print(f"[fail] {filename}：{exc}")
    if failed:
        print(f"\n{len(failed)} 个文件下载失败，词典将降级为全部 unknown", file=sys.stderr)
        return 1
    print("\n词典就绪。分析模块将自动加载（查不到的词标记为 unknown）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
