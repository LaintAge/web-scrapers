# Лабораторная работа №5. Вариант 4

## 1. Цель и вариант
* Вариант 4: quotes.toscrape.com — обход по тегам.
* Список тегов на главной + цитаты каждого тега + данные автора


## 2. Карта источника
- Точка входа: https://quotes.toscrape.com/
- Уровень 1: топ-теги на главной.
```
# body
└─ .container
   └─ .row
      └─ .col-md-4.tags-box
         └─ span.tag-item
            └─ a.tag[href="/tag/<tag>/page/1/"]
```
- Уровень 2: страницы тегов с пагинацией.
```
# body
└─ .container
   └─ .row
      ├─ .col-md-8
      │  ├─ .quote
      │  │  ├─ span.text
      │  │  ├─ span
      │  │  │  ├─ small.author
      │  │  │  └─ a[href="/author/<slug>"]
      │  │  └─ .tags
      │  │     └─ a.tag
      │  └─ .quote
      │     └─ ...
      └─ .col-md-4
         └─ ul.pager
            └─ li.next
               └─ a[href=".../page/N/"]
```

- Уровень 2.5: Карточки авторов.
```
# body
└─ .container
   └─ .row
      └─ .col-md-8
         └─ .author-details
            ├─ h3.author-title
            ├─ span.author-born-date
            ├─ span.author-born-location
            └─ .author-description
```
- Общая используемая структура.
```
https://quotes.toscrape.com/
│
├── [Уровень 1] главная → div.tags-box a.tag
│      │
│      ▼
│   https://quotes.toscrape.com/tag/<tag>/page/1/
│      │
│      ├── [Уровень 2] div.quote
│      │       ├─ span.text::text              → quote
│      │       ├─ small.author::text           → author
│      │       ├─ div.tags a.tag::text         → tags
│      │       └─ small.author + a::attr(href) → author_url
│      │
│      ├── [Уровень 2] пагинация
│      │       └─ li.next a::attr(href) → /tag/<tag>/page/N/
│      │
│      └── [Уровень 2.5] автор
│              https://quotes.toscrape.com/author/<slug>
│                  ├─ span.author-born-date::text      → author_born_date
│                  ├─ span.author-born-location::text  → author_born_place
│                  └─ div.author-description::text     → author_bio
│
└── [Уровень 1] главная → div.tags-box a.tag (следующий тег)
```

- Используемые селекторы:

| Уровень | Селектор | Поле | Тип |
|---|---|---|---|
| 1 | div.tags-box span.tag-item a.tag::text | source_tag | str |
| 1 | div.tags-box span.tag-item a.tag::attr(href) | tag_url | URL |
| 2 | span.text::text | quote | str |
| 2 | small.author::text | author | str |
| 2 | div.tags a.tag::text | tags | list[str] |
| 2 | small.author + a::attr(href) | author_url | URL |
| 2 | li.next a::attr(href) | next_page | URL |
| 2.5 | span.author-born-date::text | author_born_date | date |
| 2.5 | span.author-born-location::text | author_born_place | str |
| 2.5 | div.author-description::text | author_bio | str |



- Ключ уникальности: author + quote + source_tag.



## 3. Архитектура Scrapy
- Spider: TagsSpider.
- Item: QuoteItem.
- Pipeline: ValidatePipeline(100), CleanPipeline(200), DuplicateFilterPipeline(300), SQLitePipeline(400).
- Настройки: ROBOTSTXT_OBEY, AutoThrottle, DEPTH_LIMIT, CLOSESPIDER_ITEMCOUNT=350.

## 4. Пайплайн и счётчики
- Валидация обязательных полей
- Очистка и типизация
- Дедупликация по бизнес-ключу
- Запись в SQLite

## 5. Настройки
| Настройка | Значение | Обоснование |
|---|---|---|
| ROBOTSTXT_OBEY | True | этика и требования |
| CONCURRENT_REQUESTS_PER_DOMAIN | 4 | вежливость |
| DOWNLOAD_DELAY | 1.0 | снижение нагрузки |
| AUTOTHROTTLE_ENABLED | True | адаптивная скорость |
| CLOSESPIDER_ITEMCOUNT | 350 | предохранитель |
| DEPTH_LIMIT | 6 | ограничение глубины |

## 6. JOBDIR и HTTPCACHE
- JOBDIR: jobstate/tags_run1, dupefilter/filtered = 10
- HTTPCACHE: httpcache/store = 156, httpcache/hit = 156
- Время прогонов: 4 мин. 2 сек.

## 7. Качество данных
- Всего записей: 190
- Уникальных business_key: 190
- Полнота полей: 100%
- Причины отброса: не было
- Распределение кодов ответа: 
  - **200** - 150 (76.5%)
  - **308** - 45 (23%)
  - **404** - 1 (0.5%) (robots.txt)
  - всего **196**
- Агрегаты: топ-теги, топ-авторы, кол-во уникальных записей.

**Топ-10 тегов (по числу цитат)**

| # | Тег | Количество цитат |
|---:|---|---:|
| 1 | love | 14 |
| 2 | life | 13 |
| 3 | inspirational | 13 |
| 4 | humor | 12 |
| 5 | books | 11 |
| 6 | reading | 7 |
| 7 | friendship | 5 |
| 8 | truth | 4 |
| 9 | friends | 4 |
| 10 | writing | 3 |

**Топ-10 авторов (по числу цитат)**

| # | Автор | Количество цитат |
|---:|---|---:|
| 1 | Albert Einstein | 17 |
| 2 | Mark Twain | 13 |
| 3 | Jane Austen | 13 |
| 4 | Marilyn Monroe | 11 |
| 5 | Dr. Seuss | 9 |
| 6 | C.S. Lewis | 9 |
| 7 | John Lennon | 8 |
| 8 | Elie Wiesel | 8 |
| 9 | Madeleine L'Engle | 7 |
| 10 | George R.R. Martin | 6 |

**Уникальные авторы и теги**

| Показатель | Значение |
|---|---:|
| Уникальных авторов | 45 |
| Уникальных тегов  | 99 |
| Уникальных комбинаций тегов | 59 |


## 8. Сравнение Scrapy и n8n
| Метрика | Scrapy | n8n |
|---|---|---|
| Время разработки, мин | 3ч| 4ч|
| Записей собрано |190 | 86|
| Время прогона, с |4м 2с |2м 16с |
| Записей в минуту |48 |43 |
| Число сетевых запросов |196 | 120|
| Трафик, МБ |0.65 | не известно|
| Дедупликация запросов |есть | нет|
| Возобновление после сбоя | есть|собственная реализация |
| Расписание и оповещения | нет |есть |
| Версионирование логики | нет|есть |
| Оценка поддержки (1–5) |3 |2 |

## 9. Выводы
(а) разовый обход 500 страниц — n8n
(б) ежедневный обход 40 000 страниц — Scrapy
(в) сотня страниц + отчёт в мессенджер — n8n
Гибридный контур: n8n запускает Scrapy через Scrapyd/webhook, читает БД и отправляет отчёт.

## 10. Правовая и этическая оценка
- robots.txt соблюдается.
- Нагрузка ограничена.
- Персональные данные не собираются.
- 152-ФЗ: рисков нет.