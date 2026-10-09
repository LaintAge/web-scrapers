import json
import os
from datetime import datetime

import scrapy

from lab5_quotes.items import QuoteItem


class TagsSpider(scrapy.Spider):
    name = "tags"
    allowed_domains = ["quotes.toscrape.com"]
    start_urls = ["https://quotes.toscrape.com/"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.author_cache = {}
        self.pending_quotes = {}
        self.seen_tags = set()

    def parse(self, response):
        """Уровень 1: теги на главной."""
        for tag in response.css("div.tags-box span.tag-item a.tag"):
            tag_name = tag.css("::text").get()
            href = tag.css("::attr(href)").get()
            if not tag_name or not href:
                continue
            tag_name = tag_name.strip().lower()
            self.seen_tags.add(tag_name)
            yield response.follow(
                href,
                callback=self.parse_tag,
                errback=self.errback,
                cb_kwargs={"tag": tag_name},
            )

    def parse_tag(self, response, tag):
        """Уровень 2: цитаты на странице тега + пагинация."""
        for quote_div in response.css("div.quote"):
            quote = quote_div.css("span.text::text").get()
            author = quote_div.css("small.author::text").get()
            tags = quote_div.css("div.tags a.tag::text").getall()
            author_href = quote_div.css("span small.author + a::attr(href)").get()

            if not quote or not author or not author_href:
                self.crawler.stats.inc_value("dropped/incomplete_card")
                continue

            author_url = response.urljoin(author_href)
            item_data = {
                "quote": quote,
                "author": author,
                "tags": tags,
                "source_tag": tag,
                "author_url": author_url,
            }

            if author_url in self.author_cache:
                yield self._make_item(item_data, self.author_cache[author_url])
            else:
                if author_url not in self.pending_quotes:
                    self.pending_quotes[author_url] = []
                    yield scrapy.Request(
                        author_url,
                        callback=self.parse_author,
                        errback=self.errback,
                        cb_kwargs={"author_url": author_url},
                    )
                self.pending_quotes[author_url].append(item_data)

            # Дополнительно находим новые теги внутри цитат,
            # чтобы набрать >= 300 записей.
            for t in tags:
                t_clean = t.strip().lower()
                if t_clean and t_clean not in self.seen_tags:
                    self.seen_tags.add(t_clean)
                    yield response.follow(
                        f"/tag/{t_clean}/page/1/",
                        callback=self.parse_tag,
                        errback=self.errback,
                        cb_kwargs={"tag": t_clean},
                    )

        next_page = response.css("li.next a::attr(href)").get()
        if next_page:
            yield response.follow(
                next_page,
                callback=self.parse_tag,
                errback=self.errback,
                cb_kwargs={"tag": tag},
            )

    def parse_author(self, response, author_url):
        """Карточка автора."""
        born_date = response.css("span.author-born-date::text").get()
        born_place = response.css("span.author-born-location::text").get()
        bio_parts = response.css("div.author-description::text").getall()
        bio = " ".join(bio_parts).strip()

        author_data = {
            "author_born_date": born_date.strip() if born_date else "",
            "author_born_place": born_place.strip() if born_place else "",
            "author_bio": bio,
        }
        self.author_cache[author_url] = author_data

        for item_data in self.pending_quotes.pop(author_url, []):
            yield self._make_item(item_data, author_data)

    def _make_item(self, item_data, author_data):
        item = QuoteItem()
        item["quote"] = item_data["quote"]
        item["author"] = item_data["author"]
        item["tags"] = item_data["tags"]
        item["source_tag"] = item_data["source_tag"]
        item["author_url"] = item_data["author_url"]
        item["author_born_date"] = author_data.get("author_born_date", "")
        item["author_born_place"] = author_data.get("author_born_place", "")
        item["author_bio"] = author_data.get("author_bio", "")
        return item

    def errback(self, failure):
        self.logger.error("Request failed: %s", failure.request.url)
        self.crawler.stats.inc_value("errback/errors")

    def closed(self, reason):
        """Сохраняем статистику прогона."""
        stats = self.crawler.stats.get_stats()
        stats["close_reason"] = reason
        os.makedirs("data", exist_ok=True)
        fname = f"data/stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2, default=str)
        self.logger.info("Stats saved to %s", fname)