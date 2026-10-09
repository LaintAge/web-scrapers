import os
import re
import sqlite3
from datetime import datetime

from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem


class ValidatePipeline:
    """Валидация обязательных полей"""

    required = [
        "quote",
        "author",
        "source_tag",
        "author_born_date",
        "author_born_place",
        "author_bio",
    ]

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        missing = [field for field in self.required if not adapter.get(field)]
        if missing:
            spider.crawler.stats.inc_value("dropped/missing_fields")
            raise DropItem(f"Missing fields: {missing}")
        return item


class CleanPipeline:
    """Очистка и типизация"""

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)

        adapter["quote"] = " ".join(adapter.get("quote", "").split())
        adapter["author"] = adapter.get("author", "").strip()
        adapter["source_tag"] = adapter.get("source_tag", "").strip().lower()

        tags = adapter.get("tags", []) or []
        adapter["tags"] = [t.strip().lower() for t in tags if t and t.strip()]

        born_date = adapter.get("author_born_date", "").strip()
        try:
            dt = datetime.strptime(born_date, "%B %d, %Y")
            adapter["author_born_date"] = dt.date().isoformat()
        except Exception:
            spider.crawler.stats.inc_value("dropped/invalid_date")
            raise DropItem(f"Invalid author_born_date: {born_date}")

        place = adapter.get("author_born_place", "").strip()
        place = re.sub(r"^in\s+", "", place, flags=re.IGNORECASE)
        adapter["author_born_place"] = place

        bio = adapter.get("author_bio", "")
        adapter["author_bio"] = " ".join(bio.split())
        adapter["author_url"] = adapter.get("author_url", "").strip()

        adapter["business_key"] = (
            f"{adapter['author'].lower()}|"
            f"{adapter['quote'].lower()}|"
            f"{adapter['source_tag']}"
        )
        return item


class DuplicateFilterPipeline:
    """Дедупликация по бизнес-ключу"""

    def __init__(self):
        self.seen = set()

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        key = adapter.get("business_key")
        if key in self.seen:
            spider.crawler.stats.inc_value("dropped/duplicates")
            raise DropItem(f"Duplicate: {key}")
        self.seen.add(key)
        return item


class SQLitePipeline:
    """Пакетная запись в SQLite."""

    def __init__(self, db_path="data/crawl.db", batch_size=50):
        self.db_path = db_path
        self.batch_size = batch_size
        self.conn = None
        self.batch = []

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            db_path=crawler.settings.get("SQLITE_DB_PATH", "data/crawl.db"),
            batch_size=crawler.settings.getint("SQLITE_BATCH_SIZE", 50),
        )

    def open_spider(self, spider):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quotes (
                business_key TEXT PRIMARY KEY,
                quote TEXT NOT NULL,
                author TEXT NOT NULL,
                tags TEXT,
                source_tag TEXT NOT NULL,
                author_born_date TEXT,
                author_born_place TEXT,
                author_bio TEXT,
                author_url TEXT
            )
            """
        )
        self.conn.commit()

    def close_spider(self, spider):
        self._flush(spider)
        if self.conn:
            self.conn.close()

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        self.batch.append(
            (
                adapter.get("business_key"),
                adapter.get("quote"),
                adapter.get("author"),
                ",".join(adapter.get("tags", [])),
                adapter.get("source_tag"),
                adapter.get("author_born_date"),
                adapter.get("author_born_place"),
                adapter.get("author_bio"),
                adapter.get("author_url"),
            )
        )
        if len(self.batch) >= self.batch_size:
            self._flush(spider)
        return item

    def _flush(self, spider):
        if not self.batch:
            return
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO quotes
            (business_key, quote, author, tags, source_tag,
             author_born_date, author_born_place, author_bio, author_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self.batch,
        )
        self.conn.commit()
        spider.crawler.stats.inc_value("pipeline/sqlite_written", len(self.batch))
        self.batch.clear()