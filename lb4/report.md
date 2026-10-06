# Отчёт по лабораторной работе №4

**Тема:** Сравнение подходов к сбору данных с динамического источника: браузерная автоматизация, дешёвая альтернатива через XHR и no-code инструмент.

**Вариант 4.**
- Динамический источник: `https://www.scrapingcourse.com/javascript-rendering`
- Дешёвая альтернатива (XHR-эндпоинт): `https://www.scrapingcourse.com/ajax/products/json`
- Контрольный статический источник: `https://books.toscrape.com`

---

## 1. Цель и вариант

**Цель работы** — освоить и сравнить три подхода к сбору данных с веб-страницы, содержимое которой формируется JavaScript:

1. **Браузерный путь** — Playwright (Chromium, headless) с полной эмуляцией пользователя и запуском JS.
2. **Дешёвая альтернатива** — прямой запрос к XHR-эндпоинту через `requests`, без запуска браузера.
3. **No-code** —  Octoparse.

**Задачи:**

- Провести диагностику источника: определить, где именно формируются данные (HTML или XHR).
- Реализовать два скрипта: `playwright_collect.py` и `xhr_collect.py`.
- Замерить ключевые метрики: время выполнения, число запросов, трафик, пиковую память процесса, скорость записи.
- Оценить устойчивость использованных локаторов к редизайну.
- Сравнить три подхода и сформулировать рекомендации.

**Критерии сравнения:** скорость разработки, ресурсоёмкость прогона, устойчивость к изменениям разметки, воспроизводимость, требования к инфраструктуре.

---

## 2. Протокол диагностики источника

Диагностика выполнялась в следующем порядке:

1. **Просмотр исходного HTML.** Запрос `curl` к `https://www.scrapingcourse.com/javascript-rendering` показывает, что в HTML **есть** элементы `.product-item`, `.product-name`, `.product-price`, но в них нет данных. Значит, содержимое подгружается JavaScript-ом.

2. **Анализ сетевой активности (DevTools → Network).** При загрузке страницы браузер выполняет:
   - `GET` HTML-документа,
   - `GET` JS-бандлов,
   - `XHR GET https://www.scrapingcourse.com/ajax/products/json` — этот ответ содержит JSON с массивом товаров.

3. **Проверка XHR-эндпоинта напрямую.** `requests.get` к тому же URL с заголовками, имитирующими XHR (`X-Requested-With: XMLHttpRequest`, `Referer`, `User-Agent`), возвращает `HTTP 200` и JSON вида:

   ```json
    {
      "id": 17,
      "type": "variable",
      "sku": "MH01",
      "name": "Chaz Kangeroo Hoodie",
      "short_description": "This is a variable product called a Chaz Kangeroo Hoodie",
      "description": "<p>Ideal for cold-weather training or work outdoors, the Chaz Hoodie promises superior warmth with every wear. Thick material blocks out the wind as ribbed cuffs and bottom band seal in body heat.</p> <p>&bull; Two-tone gray heather hoodie.<br />&bull; Drawstring-adjustable hood. <br />&bull; Machine wash/dry.</p>",
      "stock": 0,
      "sale_price": "",
      "regular_price": 52,
      "categories": "Clothing>Men>Tops>Hoodies & Sweatshirts|Clothing>Collections>Eco Friendly|Clothing",
      "tags": "",
      "images": "http://eimages.valtim.com/acme-images/product/m/h/mh01-gray_main.jpg,http://eimages.valtim.com/acme-images/product/m/h/mh01-gray_alt1.jpg,http://eimages.valtim.com/acme-images/product/m/h/mh01-gray_back.jpg",
      "parent": "",
      "grouped_products": "",
      "button_text": "",
      "attr_1_name": "Size",
      "attr_1_value": "XS|S|M|L|XL",
      "attr_2_name": "Color",
      "attr_2_value": "Black|Gray|Orange",
      "attr_3_name": "",
      "attr_3_value": "",
      "attr_4_name": "",
      "attr_4_value": "",
      "attr_5_name": "",
      "attr_5_value": ""
    }
   ```

4. **Вывод диагностики.** Динамика на странице сводится к **одному** XHR-запросу. Это делает возможным «дешёвый» сбор без браузера.

---

## 3. Схема реализации

### 3.1. Браузерный путь (`playwright_collect.py`)

```
sync_playwright()
  └─ chromium.launch(headless=True)
  └─ new_context(user_agent, viewport, locale)
  └─ page.route("**/*.{png,jpg,...,mp4}", abort)   ← блокировка медиа
  └─ page.on("response", on_response)              ← замер трафика
  └─ page.goto(TARGET_URL, wait_until="commit")
  └─ page.wait_for_selector(".product-item .product-name")
  └─ while iteration < MAX_ITERATIONS:
        page.eval_on_selector_all(".product-item", JS-извлечение)
        дедупликация по (name, price)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        wait_for_function(...)  или 5-секундный таймаут
        wait_for_timeout(800)
  └─ context.close(); browser.close()
```

**Особенности:**
- Блокировка изображений, шрифтов, медиа через `page.route` (ускоряет загрузку и уменьшает трафик).
- Массовое извлечение через `eval_on_selector_all` — быстрее, чем N вызовов `query_selector`.
- Дедупликация выполняется на стороне Python, чтобы исключить дубликаты, появляющиеся при повторных запросах.
- Артефакты при сбое: скриншот и HTML сохраняются в `artifacts/`.

### 3.2. Дешёвая альтернатива (`xhr_collect.py`)

```
requests.get(XHR_URL, headers=HEADERS, timeout=30)
  └─ retry с экспоненциальной задержкой (до MAX_RETRIES)
  └─ r.json() → список товаров
  └─ product_to_row()  →  нормализация цены и slug
  └─ дедупликация по name
  └─ запись CSV + журнала
```

**Особенности:**
- Заголовки эмулируют XHR-запрос, чтобы сервер отдал JSON, а не HTML.
- Retry с backoff (`RETRY_DELAY * attempt`) при `HTTP != 200` и сетевых ошибках.
- Нормализация цены: удаление `$`, запятых, приведение к `float`.
- Никаких зависимостей от браузера — только `requests`.

### 3.3. Замеры метрик (общие для обоих скриптов)

- **Трафик**: через `page.on("response")` / `Content-Length` (браузер) или через `len(r.content)` (requests), накопительно в МБ.
- **Память**: `psutil.Process(os.getpid()).memory_info().rss` + RSS всех дочерних процессов Chromium (для Playwright).
- **Скорость записи**: таймер вокруг `writer.writerows()` → `МБ / сек`.
- **Журнал** пишется отдельным CSV/JSON, в него включены все метрики по итерациям/запуску.

---

## 4. Таблица использованных локаторов и оценка устойчивости

### 4.1. Использованные локаторы

| # | Локатор | Тип | Назначение |
|---|---|---|---|
| 1 | `.product-item` | CSS-класс | Контейнер карточки товара |
| 2 | `.product-name` | CSS-класс | Имя товара |
| 3 | `.product-price` | CSS-класс | Цена товара |
| 4 | `a.product-link` | CSS-класс на `<a>` | Ссылка на карточку товара |
| 5 | `img.product-image` | CSS-класс на `<img>` | Изображение товара |
| 6 | `meta[itemprop="sku"]` | Атрибут `itemprop` | SKU товара |

Альтернативные семантические локаторы:

| Текущий | Аналог | Назначение |
|---|---|---|
| `.product-name` | `[data-testid="product-name"]`, `[itemprop="name"]` | Имя товара |
| `.product-price` | `[data-testid="product-price"]`, `[itemprop="priceCurrency"]` | Цена |
| `a.product-link` | `a[data-testid="product-link"]`, `a[href*="/product/"]` | Ссылка |
| `.product-item` | `[itemtype="https://schema.org/Product"]` | Контейнер |

### 4.2. Что произойдёт при изменениях

| Локатор | Переименование CSS-класса | Вставка доп. `div`-обёртки | Смена текста кнопки на другой язык |
|---|---|---|---|
| `.product-name` | **Сломается**: `querySelector` вернёт `null`, поле `name` станет пустым | **Работает**: класс остаётся на элементе | **Не зависит**: локатор не опирается на текст |
| `.product-price` | **Сломается**: цена не будет извлечена | **Работает** | **Не зависит** |
| `a.product-link` | **Сломается частично**: fallback `el.querySelector('a')` найдёт любую ссылку, но может быть неверной | **Работает** | **Не зависит** |
| `meta[itemprop="sku"]` | **Работает**: атрибут не CSS-класс | **Работает** | **Не зависит** |
| `.product-item` | **Сломается**: `eval_on_selector_all` вернёт пустой массив | **Работает** | **Не зависит** |

**Вывод по устойчивости.** Большинство локаторов опираются на CSS-классы — они **устойчивы** к вставке обёрток и к смене языка, но **хрупки к переименованию классов**.

Для XHR-подхода проблема редизайна разметки вообще отсутствует — стабильность определяется контрактом API.

---

## 5. Сценарий взаимодействия и предохранители

### 5.1. Сценарий (playwright)

1. Открыть контекст с  `User-Agent`, `viewport = 1366×768`, `locale = en-US`.
2. Заблокировать изображения/шрифты/медиа.
3. Перейти на страницу с `wait_until="commit"`.
4. Дождаться появления `.product-item .product-name` (таймаут 20 с).
5. Циклически:
   - извлечь все текущие карточки массово через `eval_on_selector_all`;
   - дедуплицировать по ключу `(name, price)`;
   - прокрутить страницу вниз;
   - подождать либо появления новых элементов (`wait_for_function`, 5 с), либо таймаута;
   - пауза  800 мс.

### 5.2. Предохранители

| Предохранитель | Значение | Назначение |
|---|---|---|
| `MAX_ITERATIONS` | 10 | Не дать циклу работать бесконечно |
| `MAX_NO_GROWTH` | 3 | Остановка, если 3 итерации подряд нет новых записей |
| `MAX_RECORDS` | 500 | Жёсткий лимит объёма данных |
| `DEFAULT_TIMEOUT` | 30 000 мс | Общий таймаут операций Playwright |
| `NAVIGATION_TIMEOUT` | 45 000 мс | Таймаут навигации |
| `SELECTOR_TIMEOUT` | 20 000 мс | Ожидание появления ключевого селектора |
| `MAX_RETRIES` (XHR) | 3 | Число попыток при сетевых сбоях |
| `RETRY_DELAY` (XHR) | 2 с | База экспоненциальной задержки между попытками |

Дополнительно:
- При сбое Playwright-скрипт сохраняет `artifacts/{timeout|error}_screenshot.png` и `{...}_page.html`.
- XHR-скрипт при исчерпании ретраев возвращает `None` и корректно завершает запись журнала со `status="error"`.

---

## 6. Таблица сравнения по измеренным метрикам

| Метрика | Playwright | Дешёвая альтернатива (requests + XHR) | No-code (Octoparse) |
|---|---|---|---|
| Время разработки, мин | 60 | 10 | 5 |
| Записей собрано | 12 | 12 | 12 |
| Время одного прогона, с | 9.1 | 1.0 | 8.0 |
| Число сетевых запросов | 2 (HTML + XHR)  | 1 (только XHR) | не известно |
| Трафик, МБ | 0.012 | 0.013 | 2.1 |
| Пиковая память процесса, МБ | 414 | 37 | не известно |
| Скорость записи, МБ/с | 5.2 | 5.67 | не известно |
| Устойчивость к редизайну (1–5) | 3 | 5 | 2 |
| Воспроизводимость | Git + `requirements.txt` | Git + `requirements.txt` | авто-запуск, экспорт CSV |

**Пояснения к измерениям.**

- **Playwright.** Замер при блокировке медиа (`page.route`), `wait_until="commit"`, с явным ожиданием `.product-item .product-name`. Пиковая память включает все дочерние процессы Chromium.
- **Дешёвая альтернатива.** Один `GET` к XHR-эндпоинту через `requests`, без запуска браузера. Малый трафик объясняется отсутствием загрузки HTML и JS-бандлов.
- **No-code.** Octoparse запускался из десктоп-приложения. Время прогона — по логу задачи. Трафик и память недоступны для инструментального измерения.



---

## 7. Результаты проверки качества данных

Проверка выполняется функцией `check_quality()` для обоих скриптов и сохраняется в `quality_report.json`.

**Метрики качества:**

| Показатель | Формула | Комментарий |
|---|---|---|
| `total_records` | `len(records)` | Число собранных записей |
| `empty_ratio[field]` | доля записей с пустым `name`/`price` | Порог приемлемости: ≤ 0.05 |
| `duplicates` | `total - len(set(keys))` | Ключ: `(name, price)` |
| `non_string_values` | число нестроковых значений | Все поля должны быть строками |

**Фактические результаты на наборе из 12 товаров:**

- `total_records` = 12
- `empty_ratio["name"]` = 0.0
- `empty_ratio["price"]` = 0.0
- `duplicates` = 0 (ключ `(name, price)` уникален)
- `non_string_values` = 0

**Кросс-проверка браузерного и XHR-наборов** (`compare()`):

- `common_count` = 12 — все записи совпали по ключу `name`.
- `only_light` = `only_browser` = 0.
- `price_mismatches` = 0 — цены совпадают.

Это подтверждает, что XHR-эндпоинт отдаёт те же данные, что видит браузер после рендеринга, и «дешёвая» замена корректна.

---

## 8. Описание no-code реализации (Octoparse)

**Настройка задачи:**

1. Создан новый проект типа *Web Scraping Task*.
2. Указан URL `https://www.scrapingcourse.com/javascript-rendering`.
3. Octoparse использует встроенный браузер (на базе Chromium) — JS выполняется автоматически.
4. Автоматическое распознавание списка товаров: Octoparse предложил извлечь поля *Name*, *Price*, *Link*, *Image*.
5. Проверка предпросмотра данных — 12 записей.
6. Экспорт результата в CSV (`data_octoparse.csv`).


**Ограничения:**

- Воспроизводимость ограничена: конфигурация задачи хранится внутри приложения, экспорт в Git не предусмотрен.
- Стоимость: бесплатная версия ограничивает число задач и объём выгрузки.
- Отладка при сбое менее прозрачна, чем в коде.

---

## 9. Выводы
###
1. **Динамический источник может быть «обманут».** Диагностика показала, что вся динамика страницы сводится к одному XHR-запросу. Это типичный случай, когда «дешёвая альтернатива» полностью замещает браузер.

2. **Playwright проигрывает по ресурсам, но выигрывает по контролю.** Пиковая память 414 МБ против 37 МБ у XHR — цена за реальный JS-движок. Зато Playwright эмулирует заголовки, cookies, fingerprint, обрабатывает цепочки запросов и anti-bot.

3. **Качество данных не зависит от подхода.** Кросс-проверка `data_light.csv` и `data_browser.csv` показала полное совпадение (12/12 записей, 0 расхождений по ценам).
5. **Устойчивость локаторов.** CSS-классы хрупки к редизайну. Семантические локаторы (`itemprop`, `data-testid`) и JSON-контракт XHR устойчивее и должны быть предпочтительны.

