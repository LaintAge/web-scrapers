import json
import os
import sqlite3

DB_PATH = "data/crawl.db"
SUMMARY_PATH = "data/quality_summary.json"


def get_summary():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM quotes")
    total = cur.fetchone()[0]

    cur.execute(
        """
        SELECT COUNT(*) FROM quotes
        WHERE quote IS NULL OR quote = ''
           OR author IS NULL OR author = ''
           OR source_tag IS NULL OR source_tag = ''
           OR author_born_date IS NULL OR author_born_date = ''
           OR author_born_place IS NULL OR author_born_place = ''
           OR author_bio IS NULL OR author_bio = ''
        """
    )
    empty_required = cur.fetchone()[0]

    conn.close()
    empty_ratio = empty_required / total if total else 0.0
    return {"total": total, "empty_required_ratio": empty_ratio}


def main():
    current = get_summary()
    print("Current summary:", current)

    if not os.path.exists(SUMMARY_PATH):
        with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        print("First run: saved baseline.")
        return

    with open(SUMMARY_PATH, encoding="utf-8") as f:
        previous = json.load(f)

    prev_total = previous.get("total", 0)
    if prev_total and current["total"] < prev_total * 0.8:
        print(
            f"WARNING: total records dropped by more than 20% "
            f"({prev_total} -> {current['total']})"
        )

    if current["empty_required_ratio"] > 0.05:
        print(
            f"WARNING: empty required fields ratio = "
            f"{current['empty_required_ratio']:.2%} (> 5%)"
        )

    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()