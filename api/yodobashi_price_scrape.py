#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
import os
import random
import re
import sys
import time
from typing import Dict, List, Tuple
from urllib.parse import quote, urljoin

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

BASE = "https://www.yamada-denkiweb.com"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
)

def extra_cols(prefix: str) -> List[str]:
    return [
        f"{prefix}価格",
        f"{prefix}販売状況",
        f"{prefix}販売終了フラグ",
        f"{prefix}商品URL",
        f"{prefix}検索URL",
        f"{prefix}取得エラー",
        f"{prefix}取得メーカー",
        f"{prefix}取得製品名",
        f"{prefix}取得型番",
    ]


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def read_csv_rows(path: str) -> Tuple[List[str], List[Dict[str, str]]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSVヘッダがありません")
        rows = [dict(r) for r in reader]
        return list(reader.fieldnames), rows


def write_csv_rows(path: str, fieldnames: List[str], rows: List[Dict[str, str]]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def load_existing_output(path: str, model_col: str, prefix: str) -> Dict[str, Dict[str, str]]:
    if not os.path.exists(path):
        return {}
    try:
        _, rows = read_csv_rows(path)
    except Exception:
        return {}
    d: Dict[str, Dict[str, str]] = {}
    for r in rows:
        m = (r.get(model_col) or "").strip()
        if not m:
            continue
        # 途中再開：結果/エラーが入っていればそれを使う
        if (r.get(f"{prefix}販売状況") or "").strip() or (r.get(f"{prefix}取得エラー") or "").strip():
            d[m] = r
    return d


def search_url(model: str) -> str:
    # /search/<word>/ の形式
    return f"{BASE}/search/{quote(model)}/?category="


def stop_loading(page) -> None:
    try:
        page.evaluate("window.stop();", timeout=1000)
    except Exception:
        pass


def wait_any_content_for_search(page, timeout_ms: int) -> None:
    """
    検索結果がJSで出る前提でも、最低限「商品リンクが出た」か「0件っぽい文言」まで待つ。
    """
    js = r"""
    () => {
      const txt = document.body && document.body.innerText ? document.body.innerText : "";
      const hasProductLink = [...document.querySelectorAll("a[href]")].some(a => /\/\d{10}\//.test(a.getAttribute("href") || ""));
      const noHit = txt.includes("該当") && (txt.includes("ありません") || txt.includes("見つかりません"));
      const forbidden = txt.includes("Forbidden") || txt.includes("アクセス") && txt.includes("拒否");
      return hasProductLink || noHit || forbidden;
    }
    """
    page.wait_for_function(js, timeout=timeout_ms)


def extract_candidates_from_dom(page) -> List[str]:
    hrefs: List[str] = page.eval_on_selector_all(
        "a[href]",
        "els => els.map(e => e.getAttribute('href')).filter(Boolean)"
    )
    out: List[str] = []
    seen = set()
    for h in hrefs:
        if re.search(r"/\d{10}/", h):
            # 相対を想定
            if not h.startswith("http"):
                h = urljoin(BASE, h)
            if h not in seen:
                seen.add(h)
                out.append(h)
    return out


def parse_price_yen(text: str) -> int | None:
    m = re.search(r"[¥￥]\s*([0-9][0-9,]*)", text)
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


def parse_status(text: str) -> Tuple[str, int]:
    if "販売終了" in text or "この商品の販売は終了" in text:
        return ("販売終了", 1)
    if "在庫なし" in text:
        return ("在庫なし", 0)
    if "お取り寄せ" in text:
        return ("お取り寄せ", 0)
    if "在庫あり" in text:
        return ("在庫あり", 0)
    if "カートに入れる" in text:
        return ("ok", 0)
    return ("unknown", 0)


def extract_model_from_text(text: str) -> str:
    # 例: 「型番」近辺から拾う（ページによって崩れるので雑に）
    m = re.search(r"(?:\n|^)型番\s*\n\s*([^\n]+)", text)
    if not m:
        return ""
    return norm_ws(m.group(1))


def model_exact_in_text(model: str, text: str) -> bool:
    if not model or not text:
        return False
    pat = re.escape(model)
    return re.search(rf"(?<![A-Za-z0-9\-]){pat}(?![A-Za-z0-9\-])", text) is not None


def try_close_popups(page):
    # ありがちな同意/閉じるを雑に潰す（無くてもOK）
    for label in ["同意", "閉じる", "OK", "許可", "×"]:
        try:
            btn = page.get_by_role("button", name=label).first
            if btn.count() > 0:
                btn.click(timeout=800, no_wait_after=True)
                page.wait_for_timeout(200)
        except Exception:
            pass


def goto_page(page, url: str, timeout_ms: int, debug: bool = False) -> None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except PWTimeoutError:
        if debug:
            eprint("[goto] domcontentloaded timeout -> commit+stop")
        page.goto(url, wait_until="commit", timeout=timeout_ms)
        stop_loading(page)


def extract_product(page, model: str, timeout_ms: int, debug: bool = False) -> Dict[str, object]:
    # 少し待つ（JSで価格が入る場合）
    try:
        page.wait_for_timeout(300)
    except Exception:
        pass

    try_close_popups(page)

    body = ""
    try:
        body = page.locator("body").inner_text(timeout=timeout_ms)
    except Exception:
        body = ""

    # 価格は「価格」近辺優先
    idx = body.find("価格")
    window = body[idx: idx + 600] if idx != -1 else body[:1200]
    price = parse_price_yen(window) or parse_price_yen(body)

    status, discontinued = parse_status(body)

    name = ""
    try:
        name = norm_ws(page.locator("h1").first.inner_text(timeout=timeout_ms))
    except Exception:
        name = ""

    model_found = extract_model_from_text(body)
    if not model_found and model_exact_in_text(model, name):
        model_found = model

    if debug:
        eprint(f"[product] price={price} status={status} model_found={model_found!r}")

    return {
        "price_yen": price,
        "status": status,
        "discontinued": discontinued,
        "product_url": page.url,
        "product_name_found": name,
        "maker_found": "",
        "model_found": model_found,
    }


def route_blocking(page, no_block: bool) -> None:
    if no_block:
        return

    def _route(route):
        try:
            rtype = route.request.resource_type
            if rtype in ("image", "media", "font"):
                route.abort()
            else:
                route.continue_()
        except Exception:
            try:
                route.continue_()
            except Exception:
                pass

    page.route("**/*", _route)


def make_context(browser):
    return browser.new_context(
        locale="ja-JP",
        user_agent=UA,
        viewport={"width": 1280, "height": 900},
        extra_http_headers={"Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8"},
    )


def make_page(context, timeout_ms: int, no_block: bool):
    page = context.new_page()
    page.set_default_timeout(timeout_ms)
    page.set_default_navigation_timeout(timeout_ms)
    route_blocking(page, no_block=no_block)
    return page


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_csv")
    ap.add_argument("output_csv")
    ap.add_argument("--model-col", default="型番名")
    ap.add_argument("--prefix", default="ヤマダ")
    ap.add_argument("--timeout", type=float, default=30)
    ap.add_argument("--sleep", type=float, default=1.2)
    ap.add_argument("--sleep-jitter", type=float, default=1.0)
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--use-chrome", action="store_true")
    ap.add_argument("--no-block", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--row-retries", type=int, default=1)
    ap.add_argument("--max-candidates", type=int, default=6)
    ap.add_argument("--reset-context-every", type=int, default=20, help="N件ごとにcontextを作り直す（0で無効）")
    args = ap.parse_args()

    timeout_ms = int(args.timeout * 1000)

    in_fieldnames, in_rows = read_csv_rows(args.input_csv)

    out_fieldnames = list(in_fieldnames)
    for c in extra_cols(args.prefix):
        if c not in out_fieldnames:
            out_fieldnames.append(c)

    existing = load_existing_output(args.output_csv, args.model_col, args.prefix)

    out_rows: List[Dict[str, str]] = []
    total = len(in_rows)

    with sync_playwright() as p:
        launch_kwargs = {"headless": (not args.headful)}
        if args.use_chrome:
            launch_kwargs["channel"] = "chrome"

        browser = p.chromium.launch(**launch_kwargs)

        context = make_context(browser)
        page = make_page(context, timeout_ms=timeout_ms, no_block=args.no_block)

        try:
            for idx, row in enumerate(in_rows, start=1):
                model = (row.get(args.model_col) or "").strip()

                if model and model in existing:
                    out_rows.append(existing[model])
                    continue

                out = dict(row)
                for c in extra_cols(args.prefix):
                    out.setdefault(c, "")

                if not model:
                    out[f"{args.prefix}取得エラー"] = "no_model"
                    out_rows.append(out)
                    write_csv_rows(args.output_csv, out_fieldnames, out_rows)
                    continue

                if args.debug:
                    eprint(f"[{idx}/{total}] model={model!r}")

                out[f"{args.prefix}検索URL"] = search_url(model)

                last_exc: Exception | None = None
                data: Dict[str, object] | None = None

                for attempt in range(args.row_retries + 1):
                    try:
                        # ---- search ----
                        goto_page(page, out[f"{args.prefix}検索URL"], timeout_ms=timeout_ms, debug=args.debug)
                        wait_any_content_for_search(page, timeout_ms=timeout_ms)

                        # 候補URL抽出（/1234567890/ 形式のリンクを拾う）
                        candidates = extract_candidates_from_dom(page)
                        if args.debug:
                            eprint(f"[cand] {len(candidates)}")

                        if not candidates:
                            # 0件 or JS無効ページの可能性があるので、本文も見て判定
                            body = page.locator("body").inner_text(timeout=timeout_ms)
                            if "JavaScriptが無効" in body:
                                raise RuntimeError("search page says JavaScript disabled (render failed?)")
                            out[f"{args.prefix}販売状況"] = "not_found"
                            out[f"{args.prefix}取得エラー"] = ""
                            data = {}
                            last_exc = None
                            break

                        # ---- product: 候補を最大N件見て、型番一致優先 ----
                        picked = None
                        picked_score = -10**9

                        for u in candidates[: args.max_candidates]:
                            goto_page(page, u, timeout_ms=timeout_ms, debug=args.debug)
                            pdata = extract_product(page, model, timeout_ms=timeout_ms, debug=args.debug)

                            score = 0
                            if pdata.get("model_found") == model:
                                score += 1000
                            if model_exact_in_text(model, str(pdata.get("product_name_found") or "")):
                                score += 300
                            if isinstance(pdata.get("price_yen"), int):
                                score += 50
                            if "エアコン" in str(pdata.get("product_name_found") or ""):
                                score += 30
                            if any(w in str(pdata.get("product_name_found") or "") for w in ["リモコン", "フィルター", "アダプター", "部品"]):
                                score -= 200

                            if score > picked_score:
                                picked_score = score
                                picked = pdata

                            if score >= 1000:
                                break

                        if not picked:
                            out[f"{args.prefix}販売状況"] = "not_found"
                            out[f"{args.prefix}取得エラー"] = ""
                            data = {}
                            last_exc = None
                            break

                        data = picked
                        last_exc = None
                        break

                    except Exception as e:
                        last_exc = e
                        if args.debug:
                            eprint(f"[retry] attempt {attempt+1}/{args.row_retries+1}: {type(e).__name__}: {e}")
                        # 詰まったpageを捨てて作り直し
                        try:
                            page.close()
                        except Exception:
                            pass
                        page = make_page(context, timeout_ms=timeout_ms, no_block=args.no_block)
                        time.sleep(1.0 + attempt)

                if last_exc is not None:
                    out[f"{args.prefix}取得エラー"] = f"{type(last_exc).__name__}: {last_exc}"
                    out[f"{args.prefix}販売状況"] = "error"
                else:
                    if data is None:
                        out[f"{args.prefix}取得エラー"] = "unknown"
                        out[f"{args.prefix}販売状況"] = "error"
                    elif data == {}:
                        # not_found等
                        pass
                    else:
                        price = data.get("price_yen")
                        out[f"{args.prefix}価格"] = str(price) if isinstance(price, int) else ""
                        out[f"{args.prefix}販売状況"] = str(data.get("status") or "")
                        out[f"{args.prefix}販売終了フラグ"] = str(int(data.get("discontinued") or 0))
                        out[f"{args.prefix}商品URL"] = str(data.get("product_url") or "")
                        out[f"{args.prefix}取得メーカー"] = str(data.get("maker_found") or "")
                        out[f"{args.prefix}取得製品名"] = str(data.get("product_name_found") or "")
                        out[f"{args.prefix}取得型番"] = str(data.get("model_found") or "")
                        out[f"{args.prefix}取得エラー"] = ""

                out_rows.append(out)
                write_csv_rows(args.output_csv, out_fieldnames, out_rows)

                # N件ごとにcontextリセット（長時間安定化）
                if args.reset_context_every > 0 and (idx % args.reset_context_every == 0):
                    if args.debug:
                        eprint(f"[reset] context every {args.reset_context_every}")
                    try:
                        page.close()
                    except Exception:
                        pass
                    try:
                        context.close()
                    except Exception:
                        pass
                    context = make_context(browser)
                    page = make_page(context, timeout_ms=timeout_ms, no_block=args.no_block)

                # sleep + jitter
                base = args.sleep
                jitter = random.uniform(0.0, args.sleep_jitter) if args.sleep_jitter > 0 else 0.0
                time.sleep(max(0.0, base + jitter))

        finally:
            try:
                context.close()
            except Exception:
                pass
            browser.close()


if __name__ == "__main__":
    main()
