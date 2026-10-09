import scrapy


class QuoteItem(scrapy.Item):
    quote = scrapy.Field()
    author = scrapy.Field()
    tags = scrapy.Field()
    source_tag = scrapy.Field()
    author_born_date = scrapy.Field()
    author_born_place = scrapy.Field()
    author_bio = scrapy.Field()
    author_url = scrapy.Field()
    business_key = scrapy.Field()