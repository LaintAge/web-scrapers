import csv
import json
import os
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

try:
    import psutil
except ImportError:
    psutil = None

# Структура карточки:
#   .product-item
#     ├─ a.product-link
#     │    ├─ img.product-image
#     │    └─ .product-info
#     │         ├─ span.product-name
#     │         └─ span.product-price
#     └─ meta[itemprop="sku"]


TARGET_URL = "https://www.scrapingcourse.com/javascript-rendering"

OUTPUT_DIR = Path()
ARTIFACTS_DIR = OUTPUT_DIR / "artifacts"
OUTPUT_DIR.mkdir(exist_ok=True)
ARTIFACTS_DIR.mkdir(exist_ok=True)

DATA_FILE = OUTPUT_DIR / "data_browser.csv"
LOG_FILE = OUTPUT_DIR / "collection_log.csv"
QUALITY_FILE = OUTPUT_DIR / "quality_report.json"
METRICS_FILE = OUTPUT_DIR / "metrics_report.json"

# Предохранители
MAX_ITERATIONS = 10          # максимум циклов взаимодействия
MAX_NO_GROWTH = 3            # остановка, если 3 раза подряд нет прироста
MAX_RECORDS = 500            # жёсткий лимит записей

# Таймауты (мс)
DEFAULT_TIMEOUT = 30_000
NAVIGATION_TIMEOUT = 45_000
SELECTOR_TIMEOUT = 20_000

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
VIEWPORT = {"width": 1366, "height": 768}
LOCALE = "en-US"

TRAFFIC_BYTES = 0
TRAFFIC_RESPONSES = 0
TRAFFIC_BLOCKED = 0


# ----------------------------- УТИЛИТЫ -----------------------------

def get_memory_mb() -> float | None:
    """
    Суммарный RSS текущего процесса Python и всех дочерних
    (Chromium-процессы Playwright) в МБ.
    """
    if psutil is None:
        return None
    try:
        proc = psutil.Process(os.getpid())
        total = proc.memory_info().rss
        for child in proc.children(recursive=True):
            try:
                total += child.memory_info().rss
            except Exception:
                pass
        return round(total / (1024 * 1024), 3)
    except Exception:
        return None


def write_csv_timed(path: Path, fieldnames: list[str], rows: list[dict], label: str = "") -> dict:
    """Запись CSV с замером размера, времени и скорости (МБ/с)."""
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


def write_json_timed(path: Path, payload: dict | list, label: str = "") -> dict:
    """Запись JSON с замером размера, времени и скорости (МБ/с)."""
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    t0 = time.perf_counter()
    path.write_text(text, encoding="utf-8")
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


def on_response(response) -> None:
    """Считает примерный трафик по Content-Length."""
    global TRAFFIC_BYTES, TRAFFIC_RESPONSES
    try:
        headers = response.headers or {}
        cl = headers.get("content-length")
        if cl and cl.isdigit():
            TRAFFIC_BYTES += int(cl)
        TRAFFIC_RESPONSES += 1
    except Exception:
        pass


def make_blocker():
    """Возвращает обработчик route, который блокирует ресурсы и считает их."""
    def _block(route):
        global TRAFFIC_BLOCKED
        TRAFFIC_BLOCKED += 1
        try:
            route.abort()
        except Exception:
            pass
    return _block


# ----------------------------- АРТЕФАКТЫ -----------------------------

def save_artifacts(page, prefix: str = "error") -> None:
    """Сохраняет скриншот и HTML страницы при сбое."""
    try:
        page.screenshot(path=str(ARTIFACTS_DIR / f"{prefix}_screenshot.png"))
        (ARTIFACTS_DIR / f"{prefix}_page.html").write_text(
            page.content(), encoding="utf-8"
        )
        print(f"[artifacts] сохранены {prefix}_screenshot.png и {prefix}_page.html")
    except Exception as exc:
        print(f"[artifacts] не удалось сохранить артефакты: {exc}")


# ----------------------------- КАЧЕСТВО -----------------------------

def check_quality(records: list[dict]) -> dict:
    total = len(records)
    if total == 0:
        return {"total_records": 0, "warning": "набор данных пуст"}

    required = ["name", "price"]
    empty_ratio: dict[str, float] = {}
    for field in required:
        empty_count = sum(1 for r in records if not str(r.get(field, "")).strip())
        empty_ratio[field] = round(empty_count / total, 4)

    keys = [(r.get("name", ""), r.get("price", "")) for r in records]
    duplicates = total - len(set(keys))

    non_string = sum(1 for r in records for v in r.values() if not isinstance(v, str))

    return {
        "total_records": total,
        "empty_ratio": empty_ratio,
        "duplicates": duplicates,
        "non_string_values": non_string,
    }


# ----------------------------- СБОР -----------------------------

def collect() -> None:
    global TRAFFIC_BYTES, TRAFFIC_RESPONSES, TRAFFIC_BLOCKED

    all_products: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()
    log_rows: list[dict] = []

    iteration = 0
    no_growth_count = 0
    start_total_time = time.time()

    mem_before_launch = get_memory_mb()
    traffic_before = TRAFFIC_BYTES
    responses_before = TRAFFIC_RESPONSES
    blocked_before = TRAFFIC_BLOCKED

    mem_after_launch = None
    mem_after_load = None
    mem_after_collect = None
    mem_after_close = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport=VIEWPORT,
            locale=LOCALE,
        )
        context.set_default_timeout(DEFAULT_TIMEOUT)
        context.set_default_navigation_timeout(NAVIGATION_TIMEOUT)
        page = context.new_page()

        mem_after_launch = get_memory_mb()

        page.on("response", on_response)

        # Блокировка изображений, шрифтов и медиа
        page.route(
            "**/*.{png,jpg,jpeg,gif,svg,webp,woff,woff2,ttf,otf,mp4,webm}",
            make_blocker(),
        )

        try:
            page.goto(TARGET_URL, wait_until="commit")

            page.wait_for_selector(
                ".product-item .product-name",
                timeout=SELECTOR_TIMEOUT,
            )
            print("[playwright] данные отрисованы, .product-name найден")

            mem_after_load = get_memory_mb()

            # --- Цикл взаимодействия с предохранителями ---
            while iteration < MAX_ITERATIONS and len(all_products) < MAX_RECORDS:
                iteration += 1
                iter_start = time.time()

                iter_traffic_before = TRAFFIC_BYTES
                iter_mem_before = get_memory_mb()

                products = page.eval_on_selector_all(
                    ".product-item",
                    """els => els.map(el => {
                        const nameEl  = el.querySelector('.product-name');
                        const priceEl = el.querySelector('.product-price');
                        const linkEl  = el.querySelector('a.product-link') || el.querySelector('a');
                        const imgEl   = el.querySelector('img.product-image') || el.querySelector('img');
                        const skuEl   = el.querySelector('meta[itemprop="sku"]');
                        return {
                            name:  nameEl  ? nameEl.textContent.trim()  : '',
                            price: priceEl ? priceEl.textContent.trim() : '',
                            link:  linkEl  ? linkEl.getAttribute('href') : '',
                            image: imgEl   ? imgEl.getAttribute('src')   : '',
                            sku:   skuEl   ? skuEl.getAttribute('content') : ''
                        };
                    })""",
                )

                new_items: list[dict] = []
                for prod in products:
                    key = (prod.get("name", ""), prod.get("price", ""))
                    if prod.get("name") and key not in seen_keys:
                        seen_keys.add(key)
                        new_items.append(prod)

                all_products.extend(new_items)
                growth = len(new_items)
                duration = round(time.time() - iter_start, 2)

                iter_traffic = TRAFFIC_BYTES - iter_traffic_before
                iter_mem_after = get_memory_mb()
                iter_mem_delta = (
                    round(iter_mem_after - iter_mem_before, 3)
                    if (iter_mem_after is not None and iter_mem_before is not None)
                    else None
                )

                log_rows.append(
                    {
                        "iteration": iteration,
                        "total_elements": len(products),
                        "new_items": growth,
                        "total_collected": len(all_products),
                        "duration_sec": duration,
                        "timestamp": datetime.now().isoformat(),
                        "url": page.url,
                        "iter_traffic_mb": round(iter_traffic / (1024 * 1024), 6),
                        "iter_memory_mb": iter_mem_after,
                        "iter_memory_delta_mb": iter_mem_delta,
                    }
                )
                print(
                    f"[iteration {iteration}] всего на странице: {len(products)}, "
                    f"новых: {growth}, собрано: {len(all_products)}, "
                    f"за {duration} с, трафик итерации: "
                    f"{round(iter_traffic / (1024 * 1024), 4)} МБ, "
                    f"RSS: {iter_mem_after} МБ"
                )

                if growth == 0:
                    no_growth_count += 1
                    if no_growth_count >= MAX_NO_GROWTH:
                        print(
                            f"[stop] {MAX_NO_GROWTH} итераций без прироста — "
                            f"остановка."
                        )
                        break
                else:
                    no_growth_count = 0

                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

                try:
                    page.wait_for_function(
                        f"document.querySelectorAll('.product-item').length > {len(products)}",
                        timeout=5_000,
                    )
                except PlaywrightTimeoutError:
                    print("[wait] новых элементов после прокрутки не появилось")

                page.wait_for_timeout(800)

        except PlaywrightTimeoutError as exc:
            print(f"[timeout] {exc}")
            save_artifacts(page, prefix="timeout")
        except Exception as exc:  # noqa: BLE001
            print(f"[error] {exc}")
            save_artifacts(page, prefix="error")
        finally:
            mem_after_collect = get_memory_mb()
            context.close()
            browser.close()
            mem_after_close = get_memory_mb()

    traffic_used = TRAFFIC_BYTES - traffic_before
    responses_used = TRAFFIC_RESPONSES - responses_before
    blocked_used = TRAFFIC_BLOCKED - blocked_before

    # --- Сохранение данных ---
    write_data = write_csv_timed(
        DATA_FILE,
        ["name", "price", "link", "image", "sku"],
        all_products,
        label="data_browser",
    )

    # --- Сохранение журнала ---
    write_log = write_csv_timed(
        LOG_FILE,
        [
            "iteration",
            "total_elements",
            "new_items",
            "total_collected",
            "duration_sec",
            "timestamp",
            "url",
            "iter_traffic_mb",
            "iter_memory_mb",
            "iter_memory_delta_mb",
        ],
        log_rows,
        label="collection_log",
    )

    # --- Проверка качества ---
    quality = check_quality(all_products)
    write_quality = write_json_timed(QUALITY_FILE, quality, label="quality_report")

    total_time = round(time.time() - start_total_time, 2)

    # --- Итоговые метрики ---
    metrics = {
        "total_records": len(all_products),
        "total_time_sec": total_time,
        "traffic": {
            "traffic_mb": round(traffic_used / (1024 * 1024), 6),
            "responses": responses_used,
            "blocked_requests": blocked_used,
        },
        "memory_mb": {
            "before_launch": mem_before_launch,
            "after_launch": mem_after_launch,
            "after_page_load": mem_after_load,
            "after_collect": mem_after_collect,
            "after_close": mem_after_close,
            "peak_observed": max(
                [v for v in [
                    mem_before_launch,
                    mem_after_launch,
                    mem_after_load,
                    mem_after_collect,
                    mem_after_close,
                ] if v is not None],
                default=None,
            ),
        },
        "write": {
            "data": write_data,
            "log": write_log,
            "quality": write_quality,
        },
        "psutil_available": psutil is not None,
    }

    write_metrics = write_json_timed(METRICS_FILE, metrics, label="metrics_report")
    metrics["write"]["metrics"] = write_metrics

    METRICS_FILE.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n" + "=" * 60)
    print("ИТОГИ СБОРА")
    print("=" * 60)
    print(f"Всего записей: {len(all_products)}")
    print(f"Время выполнения: {total_time} с")
    print(f"Данные: {DATA_FILE.resolve()}")
    print(f"Журнал: {LOG_FILE.resolve()}")
    print(f"Качество: {QUALITY_FILE.resolve()}")
    print(f"Метрики: {METRICS_FILE.resolve()}")

    print("\n--- Метрики ---")
    print(
        f"Трафик: {metrics['traffic']['traffic_mb']} МБ "
        f"({metrics['traffic']['responses']} ответов, "
        f"заблокировано запросов: {metrics['traffic']['blocked_requests']})"
    )
    print(
        f"Память RSS, МБ: до запуска={mem_before_launch}, "
        f"после launch={mem_after_launch}, "
        f"после загрузки={mem_after_load}, "
        f"после сбора={mem_after_collect}, "
        f"после закрытия={mem_after_close}, "
        f"пик={metrics['memory_mb']['peak_observed']}"
    )
    print(
        f"Запись {write_data['file']}: {write_data['size_mb']} МБ "
        f"за {write_data['duration_sec']} с = {write_data['speed_mb_s']} МБ/с"
    )
    print(
        f"Запись {write_log['file']}: {write_log['size_mb']} МБ "
        f"за {write_log['duration_sec']} с = {write_log['speed_mb_s']} МБ/с"
    )
    print(
        f"Запись {write_quality['file']}: {write_quality['size_mb']} МБ "
        f"за {write_quality['duration_sec']} с = {write_quality['speed_mb_s']} МБ/с"
    )

    print("\nПроверка качества:")
    print(json.dumps(quality, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    collect()