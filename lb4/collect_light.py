import csv
import json
import os
import time
from datetime import datetime
from pathlib import Path

import requests

try:
    import psutil
except ImportError:
    psutil = None


XHR_URL = "https://www.scrapingcourse.com/ajax/products/json"

OUTPUT_DIR = Path()
OUTPUT_DIR.mkdir(exist_ok=True)

DATA_LIGHT_FILE = OUTPUT_DIR / "data_light.csv"
LOG_LIGHT_FILE = OUTPUT_DIR / "light_log.csv"
DATA_BROWSER_FILE = OUTPUT_DIR / "data_browser.csv"
COMPARISON_FILE = OUTPUT_DIR / "comparison_report.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.scrapingcourse.com/javascript-rendering",
}

MAX_RETRIES = 3       # число попыток
RETRY_DELAY = 2       # база задержки между попытками (сек)

# Счётчики трафика за весь запуск
TRAFFIC_BYTES = 0
TRAFFIC_REQUESTS = 0


def normalize_price(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace("$", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def product_to_row(item: dict) -> dict:
    name = (item.get("name") or "").strip()
    sku = (item.get("sku") or "").strip()

    price = normalize_price(item.get("sale_price") or item.get("regular_price"))

    slug = name.lower().replace("  ", " ").replace(" ", "-")
    link = f"https://www.scrapingcourse.com/ecommerce/product/{slug}"

    images = item.get("images") or ""
    image = images.split(",")[0].strip() if images else ""

    return {
        "name": name,
        "sku": sku,
        "price": price,
        "link": link,
        "image": image,
    }


def response_size_bytes(r: requests.Response) -> int:
    """Приблизительный размер ответа в байтах: Content-Length или длина тела."""
    content_length = r.headers.get("Content-Length")
    if content_length and content_length.isdigit():
        return int(content_length)
    return len(r.content)


def get_memory_mb() -> float | None:
    """RSS процесса в МБ. Если psutil нет — None."""
    if psutil is None:
        return None
    try:
        process = psutil.Process(os.getpid())
        return round(process.memory_info().rss / (1024 * 1024), 3)
    except Exception:
        return None


def write_csv_timed(path: Path, fieldnames: list[str], rows: list[dict], label: str = "") -> dict:
    """Запись CSV с замером времени и скорости."""
    t0 = time.perf_counter()
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    duration = time.perf_counter() - t0
    size_mb = path.stat().st_size / (1024 * 1024)
    speed_mb_s = size_mb / duration if duration > 0 else 0.0

    return {
        "file": path.name,
        "label": label,
        "size_mb": round(size_mb, 6),
        "duration_sec": round(duration, 6),
        "speed_mb_s": round(speed_mb_s, 6),
    }


def fetch_json(url: str, retries: int = MAX_RETRIES) -> list | dict | None:
    global TRAFFIC_BYTES, TRAFFIC_REQUESTS

    attempt = 0
    last_error = None
    while attempt < retries:
        attempt += 1
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)

            size = response_size_bytes(r)
            TRAFFIC_BYTES += size
            TRAFFIC_REQUESTS += 1

            if r.status_code == 200:
                return r.json()

            last_error = f"HTTP {r.status_code}"
            print(f"[retry {attempt}/{retries}] {last_error}")
        except requests.RequestException as exc:
            last_error = str(exc)
            print(f"[retry {attempt}/{retries}] ошибка: {exc}")
        except json.JSONDecodeError as exc:
            last_error = f"JSON decode error: {exc}"
            print(f"[retry {attempt}/{retries}] {last_error}")

        if attempt < retries:
            time.sleep(RETRY_DELAY * attempt)

    print(f"[error] не удалось получить данные: {last_error}")
    return None


def collect() -> tuple[list[dict], dict]:
    print(f"[light] GET {XHR_URL}")
    started = datetime.now()
    t0 = time.time()

    mem_start = get_memory_mb()
    traffic_before = TRAFFIC_BYTES
    requests_before = TRAFFIC_REQUESTS

    data = fetch_json(XHR_URL)
    duration = round(time.time() - t0, 2)

    mem_after_fetch = get_memory_mb()
    traffic_used = TRAFFIC_BYTES - traffic_before
    requests_used = TRAFFIC_REQUESTS - requests_before

    if data is None:
        print("[light] данные не получены")
        return [], {
            "traffic_mb": round(traffic_used / (1024 * 1024), 6),
            "traffic_requests": requests_used,
            "memory_start_mb": mem_start,
            "memory_after_fetch_mb": mem_after_fetch,
        }

    if isinstance(data, dict):
        items = data.get("data") or data.get("items") or data.get("products") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []

    print(f"[light] получено элементов: {len(items)}, за {duration} с")

    rows: list[dict] = []
    seen: set[str] = set()
    for item in items:
        row = product_to_row(item)
        key = row["name"]
        if key and key not in seen:
            seen.add(key)
            rows.append(row)

    print(f"[light] после дедупликации по name: {len(rows)}")

    mem_after_parse = get_memory_mb()

    data_write = write_csv_timed(
        DATA_LIGHT_FILE,
        ["name", "sku", "price", "link", "image"],
        rows,
        label="data_light",
    )

    log_fields = [
        "attempt", "status", "items", "unique", "duration_sec", "timestamp", "url",
        "traffic_mb", "traffic_requests",
        "memory_start_mb", "memory_after_fetch_mb", "memory_after_parse_mb",
        "write_data_size_mb", "write_data_sec", "write_data_speed_mb_s",
    ]

    log_row = {
        "attempt": 1,
        "status": "ok",
        "items": len(items),
        "unique": len(rows),
        "duration_sec": duration,
        "timestamp": started.isoformat(),
        "url": XHR_URL,
        "traffic_mb": round(traffic_used / (1024 * 1024), 6),
        "traffic_requests": requests_used,
        "memory_start_mb": mem_start,
        "memory_after_fetch_mb": mem_after_fetch,
        "memory_after_parse_mb": mem_after_parse,
        "write_data_size_mb": data_write["size_mb"],
        "write_data_sec": data_write["duration_sec"],
        "write_data_speed_mb_s": data_write["speed_mb_s"],
    }

    log_write = write_csv_timed(
        LOG_LIGHT_FILE,
        log_fields,
        [log_row],
        label="light_log",
    )

    metrics = {
        "traffic_mb": round(traffic_used / (1024 * 1024), 6),
        "traffic_requests": requests_used,
        "memory_start_mb": mem_start,
        "memory_after_fetch_mb": mem_after_fetch,
        "memory_after_parse_mb": mem_after_parse,
        "write_data": data_write,
        "write_log": log_write,
    }

    print(f"[light] данные: {DATA_LIGHT_FILE.resolve()}")
    print(f"[light] журнал: {LOG_LIGHT_FILE.resolve()}")
    return rows, metrics


def load_browser_data() -> list[dict]:
    if not DATA_BROWSER_FILE.exists():
        print(f"[compare] {DATA_BROWSER_FILE} не найден — сверка пропущена.")
        return []

    rows: list[dict] = []
    with open(DATA_BROWSER_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["price"] = normalize_price(row.get("price"))
            rows.append(row)

    print(f"[compare] загружено {len(rows)} записей из {DATA_BROWSER_FILE.name}")
    return rows


def compare(light: list[dict], browser: list[dict]) -> dict:
    if not browser:
        return {"status": "skipped", "reason": "data_browser.csv отсутствует"}

    light_keys = {r["name"] for r in light if r.get("name")}
    browser_keys = {r["name"] for r in browser if r.get("name")}

    only_light = light_keys - browser_keys
    only_browser = browser_keys - light_keys
    common = light_keys & browser_keys

    light_map = {r["name"]: r["price"] for r in light if r.get("name")}
    browser_map = {r["name"]: r["price"] for r in browser if r.get("name")}

    price_mismatches = []
    for key in common:
        lp, bp = light_map.get(key), browser_map.get(key)
        if lp is not None and bp is not None and abs(lp - bp) > 0.01:
            price_mismatches.append({"name": key, "light_price": lp, "browser_price": bp})

    report = {
        "status": "ok",
        "key_field": "name",
        "light_count": len(light),
        "browser_count": len(browser),
        "common_count": len(common),
        "only_light": sorted(only_light),
        "only_browser": sorted(only_browser),
        "price_mismatches": price_mismatches,
        "counts_match": len(light) == len(browser),
        "keys_match": not only_light and not only_browser,
    }

    report_json = json.dumps(report, ensure_ascii=False, indent=2)
    t0 = time.perf_counter()
    COMPARISON_FILE.write_text(report_json, encoding="utf-8")
    write_duration = time.perf_counter() - t0
    size_mb = COMPARISON_FILE.stat().st_size / (1024 * 1024)
    speed_mb_s = size_mb / write_duration if write_duration > 0 else 0.0

    report["write_report"] = {
        "file": COMPARISON_FILE.name,
        "size_mb": round(size_mb, 6),
        "duration_sec": round(write_duration, 6),
        "speed_mb_s": round(speed_mb_s, 6),
    }

    COMPARISON_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[compare] запись отчёта: {size_mb:.6f} МБ за {write_duration:.6f} с = {speed_mb_s:.6f} МБ/с")

    print("\n" + "=" * 60)
    print("СВЕРКА НАБОРОВ (ключ: name)")
    print("=" * 60)
    print(f"data_light.csv:   {len(light)} записей")
    print(f"data_browser.csv: {len(browser)} записей")
    print(f"общих ключей:     {len(common)}")
    print(f"только в light:   {len(only_light)}")
    print(f"только в browser: {len(only_browser)}")
    print(f"расхождений цен:  {len(price_mismatches)}")

    if only_light:
        print("\nТолько в light (первые 5):")
        for k in sorted(only_light)[:5]:
            print(f"  {k}")
    if only_browser:
        print("\nТолько в browser (первые 5):")
        for k in sorted(only_browser)[:5]:
            print(f"  {k}")
    if price_mismatches:
        print("\nРасхождения цен (первые 5):")
        for m in price_mismatches[:5]:
            print(f"  {m['name']}: light={m['light_price']}, browser={m['browser_price']}")

    print(f"\n[compare] отчёт: {COMPARISON_FILE.resolve()}")
    return report


if __name__ == "__main__":
    print("=" * 70)
    print("Дешёвая альтернатива: сбор через XHR-эндпоинт (без пагинации)")
    print("=" * 70)

    light, light_metrics = collect()

    if light:
        print("\n--- Метрики light ---")
        print(
            f"Трафик: {light_metrics.get('traffic_mb')} МБ "
            f"({light_metrics.get('traffic_requests')} запросов)"
        )
        print(
            f"Память RSS, МБ: старт={light_metrics.get('memory_start_mb')}, "
            f"после fetch={light_metrics.get('memory_after_fetch_mb')}, "
            f"после парсинга={light_metrics.get('memory_after_parse_mb')}"
        )

        wd = light_metrics.get("write_data", {})
        print(
            f"Запись {wd.get('file')}: {wd.get('size_mb')} МБ "
            f"за {wd.get('duration_sec')} с = {wd.get('speed_mb_s')} МБ/с"
        )

        wl = light_metrics.get("write_log", {})
        print(
            f"Запись {wl.get('file')}: {wl.get('size_mb')} МБ "
            f"за {wl.get('duration_sec')} с = {wl.get('speed_mb_s')} МБ/с"
        )

        print("\n--- Загрузка браузерного набора ---")
        browser = load_browser_data()
        if browser:
            print("\n--- Сверка ---")
            compare(light, browser)

    print("\nГотово.")