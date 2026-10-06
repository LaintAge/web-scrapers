import json
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

DYNAMIC_URL = "https://www.scrapingcourse.com/javascript-rendering"
STATIC_URL = "https://books.toscrape.com/"

# Структура карточки:
# .product-item
#   ├─ a.product-link
#   │    ├─ img.product-image
#   │    └─ .product-info
#   │         ├─ span.product-name
#   │         └─ span.product-price
#   └─ meta[itemprop="sku"]

PRODUCT_ITEM_SELECTORS = [
    "[data-testid='product-item']",
    ".product-item",
    "#product-grid > .product-item",
    "#product-grid > div",
    ".product-item .product-name",
    ".product-item .product-price",
]

STATIC_BOOK_SELECTORS = [
    "article.product_pod",
    ".product_pod",
    "ol.row > li",
    "article.product_pod h3 a",
    ".price_color",
]

GRID_SELECTOR = "#product-grid"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

ARTIFACTS_DIR = Path("artifacts")
ARTIFACTS_DIR.mkdir(exist_ok=True)


def count_by_selectors(html: str, selectors: list[str]) -> dict[str, int]:
    soup = BeautifulSoup(html, "lxml")
    counts: dict[str, int] = {}
    for sel in selectors:
        try:
            counts[sel] = len(soup.select(sel))
        except Exception as exc:
            counts[sel] = -1
            print(f"[warn] селектор '{sel}' упал: {exc}")
    return counts


def find_markers(html: str) -> dict[str, bool]:
    lowered = html.lower()
    return {
        "has_word_product": "product" in lowered,
        "has_word_price": "price" in lowered,
        "has_application_json": "application/json" in lowered,
        "has_json_ld": "application/ld+json" in lowered,
        "has_next_data": "__next_data__" in lowered,
        "has_script_tags": "<script" in lowered,
    }


def has_grid_structure(html: str, grid_selector: str = GRID_SELECTOR) -> dict:
    soup = BeautifulSoup(html, "lxml")
    grid = soup.select_one(grid_selector)
    if grid is None:
        return {"present": False, "child_divs": 0, "child_product_items": 0}

    child_divs = len(grid.find_all("div", recursive=False))
    child_items = len(grid.select(".product-item"))

    return {
        "present": True,
        "child_divs": child_divs,
        "child_product_items": child_items,
        "grid_attrs": {
            k: v for k, v in grid.attrs.items()
            if k in ("id", "class", "data-testid")
        },
    }


def extract_static_sample_items(html: str, limit: int = 3) -> list[dict]:
    """Достаёт первые N карточек из статического HTML. """
    soup = BeautifulSoup(html, "lxml")
    items = soup.select(".product-item")
    sample: list[dict] = []

    if items:
        for el in items[:limit]:
            name_el = el.select_one(".product-name")
            price_el = el.select_one(".product-price")
            link_el = el.select_one("a.product-link") or el.select_one("a")
            img_el = el.select_one("img.product-image") or el.select_one("img")
            sku_el = el.select_one('meta[itemprop="sku"]')
            sample.append({
                "name": name_el.get_text(strip=True) if name_el else "",
                "price": price_el.get_text(strip=True) if price_el else "",
                "link": link_el.get("href", "") if link_el else "",
                "image": img_el.get("src", "") if img_el else "",
                "sku": sku_el.get("content", "") if sku_el else "",
            })
        return sample

    pods = soup.select("article.product_pod")
    for el in pods[:limit]:
        name_el = el.select_one("h3 a")
        price_el = el.select_one(".price_color")
        img_el = el.select_one("img")
        sample.append({
            "name": name_el.get("title", "").strip() if name_el else "",
            "price": price_el.get_text(strip=True) if price_el else "",
            "link": name_el.get("href", "") if name_el else "",
            "image": img_el.get("src", "") if img_el else "",
        })
    return sample


def count_data_bearing_items(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    items = soup.select(".product-item")
    with_name = [el for el in items if el.select_one(".product-name")]
    with_price = [el for el in items if el.select_one(".product-price")]
    names = [el.select_one(".product-name").get_text(strip=True) for el in with_name]
    prices = [el.select_one(".product-price").get_text(strip=True) for el in with_price]

    if not items:
        pods = soup.select("article.product_pod")
        with_name = [el for el in pods if el.select_one("h3 a")]
        with_price = [el for el in pods if el.select_one(".price_color")]
        names = [el.select_one("h3 a").get("title", "") for el in with_name]
        prices = [el.select_one(".price_color").get_text(strip=True) for el in with_price]

    return {
        "total_items": len(items) if items else len(soup.select("article.product_pod")),
        "items_with_name": len(with_name),
        "items_with_price": len(with_price),
        "sample_names": names[:3],
        "sample_prices": prices[:3],
    }


# ---------------------------------------------------------------------------
# Диагностика статического источника (requests)
# ---------------------------------------------------------------------------

def diagnose_requests(url: str, selectors: list[str]) -> dict:
    print(f"\n[requests] GET {url}")
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
    except Exception as exc:  # noqa: BLE001
        print(f"[requests] ошибка: {exc}")
        return {"url": url, "error": str(exc)}

    html = response.text
    result = {
        "url": url,
        "status_code": response.status_code,
        "html_size_bytes": len(response.content),
        "selector_counts": count_by_selectors(html, selectors),
        "grid": has_grid_structure(html),
        "markers": find_markers(html),
        "data_bearing": count_data_bearing_items(html),
        "sample_items": extract_static_sample_items(html, limit=3),
    }

    fname = ARTIFACTS_DIR / f"static_{url.rstrip('/').split('/')[-1] or 'root'}.html"
    fname.write_text(html, encoding="utf-8")
    result["saved_html"] = str(fname)

    print(f"[requests] статус: {result['status_code']}, размер: {result['html_size_bytes']} байт")
    print(f"[requests] каркас {GRID_SELECTOR}: {result['grid']}")
    print(f"[requests] счётчики селекторов: {result['selector_counts']}")
    print(f"[requests] маркеры: {result['markers']}")
    print(f"[requests] карточек с данными: {result['data_bearing']}")
    print(f"[requests] примеры из статического HTML:")
    print(json.dumps(result["sample_items"], ensure_ascii=False, indent=2))
    print(f"[requests] HTML сохранён в {fname}")

    return result


# ---------------------------------------------------------------------------
# Диагностика браузерного источника (Playwright)
# ---------------------------------------------------------------------------

def extract_sample_items(page, limit: int = 3) -> list[dict]:
    return page.eval_on_selector_all(
        ".product-item",
        f"""els => els.slice(0, {limit}).map(el => {{
            const nameEl  = el.querySelector('.product-name');
            const priceEl = el.querySelector('.product-price');
            const linkEl  = el.querySelector('a.product-link') || el.querySelector('a');
            const imgEl   = el.querySelector('img.product-image') || el.querySelector('img');
            const skuEl   = el.querySelector('meta[itemprop="sku"]');
            return {{
                name:  nameEl  ? nameEl.textContent.trim()  : '',
                price: priceEl ? priceEl.textContent.trim() : '',
                link:  linkEl  ? linkEl.getAttribute('href') : '',
                image: imgEl   ? imgEl.getAttribute('src')   : '',
                sku:   skuEl   ? skuEl.getAttribute('content') : ''
            }};
        }})"""
    )


def diagnose_browser(url: str, selectors: list[str]) -> dict:
    print(f"\n[playwright] goto {url}")
    result: dict = {"url": url, "browser_selector_counts": {}, "error": None}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )
        context.set_default_timeout(30000)
        context.set_default_navigation_timeout(45000)
        page = context.new_page()

        page.route(
            "**/*.{png,jpg,jpeg,gif,svg,webp,woff,woff2,ttf,mp4,webm}",
            lambda route: route.abort(),
        )

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)

            try:
                page.wait_for_selector(".product-item .product-name", timeout=20000)
                result["waited_for"] = ".product-item .product-name"
            except PlaywrightTimeoutError:
                result["waited_for"] = None
                result["wait_timeout"] = True

            for sel in selectors:
                try:
                    result["browser_selector_counts"][sel] = page.locator(sel).count()
                except Exception as exc:  # noqa: BLE001
                    result["browser_selector_counts"][sel] = -1
                    print(f"[playwright] селектор '{sel}' упал: {exc}")

            result["browser_selector_counts"][".product-item .product-name"] = (
                page.locator(".product-item .product-name").count()
            )
            result["browser_selector_counts"][".product-item .product-price"] = (
                page.locator(".product-item .product-price").count()
            )

            result["grid_present"] = page.locator(GRID_SELECTOR).count() > 0
            result["title"] = page.title()
            result["final_url"] = page.url

            if result["browser_selector_counts"].get(".product-item .product-name", 0) > 0:
                result["sample_items"] = extract_sample_items(page, limit=3)
            else:
                result["sample_items"] = []

            rendered_html = page.content()
            fname = ARTIFACTS_DIR / "rendered_page.html"
            fname.write_text(rendered_html, encoding="utf-8")
            result["saved_html"] = str(fname)
            result["rendered_html_size_bytes"] = len(rendered_html.encode("utf-8"))

        except Exception as exc:
            result["error"] = str(exc)
            print(f"[playwright] ошибка: {exc}")
            try:
                page.screenshot(path=str(ARTIFACTS_DIR / "error_screenshot.png"))
                (ARTIFACTS_DIR / "error_page.html").write_text(page.content(), encoding="utf-8")
            except Exception:
                pass
        finally:
            context.close()
            browser.close()

    print(f"[playwright] итоговый URL: {result.get('final_url')}")
    print(f"[playwright] title: {result.get('title')}")
    print(f"[playwright] каркас {GRID_SELECTOR}: {result.get('grid_present')}")
    print(f"[playwright] счётчики: {result['browser_selector_counts']}")
    print(f"[playwright] примеры из браузера:")
    print(json.dumps(result.get("sample_items", []), ensure_ascii=False, indent=2))
    
    return result


def build_conclusion(dynamic_req: dict, dynamic_browser: dict) -> dict:
    static_data = dynamic_req.get("data_bearing", {})
    static_with_name = static_data.get("items_with_name", 0)
    static_with_price = static_data.get("items_with_price", 0)
    static_total = static_data.get("total_items", 0)

    browser_counts = dynamic_browser.get("browser_selector_counts", {})
    browser_with_name = browser_counts.get(".product-item .product-name", 0)
    browser_with_price = browser_counts.get(".product-item .product-price", 0)

    target_met = max(static_with_name, browser_with_name) >= 200

    browser_required = (static_with_name == 0) or (not target_met)

    return {
        "static_items": static_total,
        "static_items_with_name": static_with_name,
        "static_items_with_price": static_with_price,
        "browser_items_with_name": browser_with_name,
        "browser_items_with_price": browser_with_price,
        "target_200_reached": target_met,
        "browser_required": browser_required,
    }


if __name__ == "__main__":
    print("=" * 70)
    print("Диагностика динамического источника (javascript-rendering)")
    print("=" * 70)
    dynamic_req = diagnose_requests(DYNAMIC_URL, PRODUCT_ITEM_SELECTORS)

    print("\n" + "=" * 70)
    print("Диагностика контрольного статического источника (books.toscrape.com)")
    print("=" * 70)
    static_req = diagnose_requests(STATIC_URL, STATIC_BOOK_SELECTORS)

    print("\n" + "=" * 70)
    print("Диагностика того же динамического источника через Playwright")
    print("=" * 70)
    dynamic_browser = diagnose_browser(DYNAMIC_URL, PRODUCT_ITEM_SELECTORS)

    conclusion = build_conclusion(dynamic_req, dynamic_browser)

    report = {
        "dynamic_requests": dynamic_req,
        "static_requests": static_req,
        "dynamic_browser": dynamic_browser,
        "conclusion": conclusion,
    }

    out = Path("diagnostics.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 70)
    print("ИТОГОВЫЙ ВЫВОД")
    print("=" * 70)
    print(json.dumps(conclusion, ensure_ascii=False, indent=2))
    print(f"\nОтчёт сохранён: {out.resolve()}")
    print(f"Артефакты: {ARTIFACTS_DIR.resolve()}")