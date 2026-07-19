#!/usr/bin/env python3
"""Дайджест свежей практики с sudact.ru по списку статей.

Для каждой статьи из fresh_practice_articles.txt тянет свежие акты
(первая инстанция / апелляция / кассация) за последние 12 месяцев,
сохраняет полные тексты и собирает digest.md. Повторные запуски
докачивают только новое (seen_ids.txt).

Запуск: python3 sudact_digest.py [базовая_папка_fresh_practice]
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

BASE = "https://sudact.ru"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
ARTICLES_FILE = os.path.join(TOOLS_DIR, "fresh_practice_articles.txt")
OUT_BASE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(TOOLS_DIR, "..", "knowledge", "fresh_practice")

STAGES = [("10", "Первая инстанция"), ("20", "Апелляция"), ("30", "Кассация")]
MAX_NEW_PER_ARTICLE = 25          # лимит новых текстов за запуск
MAX_PAGES_PER_STAGE = 3
SLEEP = 2.5
DOC_TEXT_LIMIT = 150_000


def http_get(url, referer=None, xhr=False, retries=4):
    """GET с ретраями: sudact периодически отдаёт 502/503, и без повтора
    статья молча выпадала из ежемесячного дайджеста."""
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url)
        req.add_header("User-Agent", UA)
        if referer:
            req.add_header("Referer", referer)
        if xhr:
            req.add_header("X-Requested-With", "XMLHttpRequest")
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500:
                raise
        except Exception as e:  # таймауты, обрывы соединения
            last = e
        time.sleep(5 * (attempt + 1))
    raise last


def resolve_law(term):
    """Автокомплит sudact: '171.1 УК' -> полное имя статьи для фильтра."""
    url = f"{BASE}/autocomplete/regular/lawchunkinfo/?term=" + urllib.parse.quote_plus(term)
    try:
        items = json.loads(http_get(url, referer=f"{BASE}/regular/doc/", xhr=True))
        return items[0] if items else None
    except Exception as e:
        print(f"  autocomplete FAIL {term}: {e}")
        return None


def search_ids(law, stage, date_from, date_to):
    """Все doc-id по статье и инстанции (с пагинацией)."""
    ids, titles = [], {}
    for page in range(1, MAX_PAGES_PER_STAGE + 1):
        params = {
            "regular-lawchunkinfo": law,
            "regular-workflow_stage": stage,
            "regular-date_from": date_from,
            "regular-date_to": date_to,
            "_": str(int(time.time() * 1000)),
        }
        if page > 1:
            params["page"] = str(page)
        url = f"{BASE}/regular/doc_ajax/?" + urllib.parse.urlencode(params)
        # Поиск асинхронный: первый вызов ставит задачу ({"status":"new"}),
        # повтор ТОГО ЖЕ URL возвращает finished с контентом.
        content = ""
        try:
            for _attempt in range(5):
                j = json.loads(http_get(url, referer=f"{BASE}/regular/doc/", xhr=True))
                content = (j.get("content") or "").strip()
                if j.get("search_status") == "finished" and content:
                    break
                time.sleep(3)
        except Exception as e:
            print(f"  search FAIL stage={stage} p{page}: {e}")
            break
        found = re.findall(r'href="/regular/doc/([A-Za-z0-9]+)/[^"]*"[^>]*>(.*?)</a>', content)
        new_here = 0
        for did, title in found:
            title = re.sub(r"<[^>]+>|\s+", " ", title).strip()
            if did not in titles and len(title) > 15:
                titles[did] = title
                ids.append(did)
                new_here += 1
        if new_here == 0:
            break
        time.sleep(SLEEP)
    return ids, titles


def fetch_doc_text(doc_id):
    html = http_get(f"{BASE}/regular/doc/{doc_id}/")
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    title = re.sub(r"<[^>]+>|\s+", " ", h1.group(1)).strip() if h1 else doc_id
    court = re.search(r'href="/regular/court/[^"]+"[^>]*>([^<]+)<', html)
    body_start = html.find('<hr class="hr-h1">')
    if body_start < 0:
        return title, (court.group(1).strip() if court else ""), ""
    body = html[body_start:]
    for stop in ("Суд:\n", 'class="footer', "▲наверх", "<!--AdFox START-->"):
        cut = body.find(stop, 100)
        if cut > 0:
            body = body[:cut]
    body = re.sub(r"<script.*?</script>", " ", body, flags=re.S)
    body = re.sub(r"<br\s*/?\s*>", "\n", body)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return title, (court.group(1).strip() if court else ""), body[:DOC_TEXT_LIMIT]


def slug_for(term):
    m = re.search(r"[\d.]+", term)
    code = "uk" if "УК" in term.upper() else ("koap" if "КОАП" in term.upper() else "law")
    return f"{code}_{m.group(0) if m else term}".replace(" ", "_")


def rebuild_digest(art_dir, term, law):
    cases_dir = os.path.join(art_dir, "cases")
    entries = []
    for fn in sorted(os.listdir(cases_dir), reverse=True) if os.path.isdir(cases_dir) else []:
        if not fn.endswith(".txt"):
            continue
        with open(os.path.join(cases_dir, fn), encoding="utf-8") as f:
            head = [next(f, "").strip() for _ in range(4)]
        entries.append((fn, head))
    with open(os.path.join(art_dir, "digest.md"), "w", encoding="utf-8") as f:
        f.write(f"# Свежая практика: {term}\n\n")
        f.write(f"Статья (фильтр sudact): {law}\n")
        f.write(f"Обновлено: {datetime.now():%Y-%m-%d}. Всего актов: {len(entries)}.\n")
        f.write("Полные тексты — в `cases/` (имя файла = дата акта + id sudact).\n"
                "Свежие публикации на sudact отстают от дат актов на несколько месяцев (обезличивание).\n\n")
        for fn, head in entries:
            title = head[0].lstrip("# ")
            meta = " · ".join(x for x in head[1:] if x and not x.startswith("http"))
            url = next((x for x in head if x.startswith("http")), "")
            f.write(f"- **{title}**\n  {meta}\n  файл: `cases/{fn}`  {url}\n")


def process_article(term):
    print(f"== {term}")
    law = resolve_law(term)
    if not law:
        print("  статья не найдена в автокомплите, пропуск")
        return
    art_dir = os.path.join(OUT_BASE, slug_for(term))
    cases_dir = os.path.join(art_dir, "cases")
    os.makedirs(cases_dir, exist_ok=True)
    seen_path = os.path.join(art_dir, "seen_ids.txt")
    seen = set()
    if os.path.exists(seen_path):
        seen = set(open(seen_path, encoding="utf-8").read().split())

    date_to = datetime.now()
    date_from = date_to - timedelta(days=365)
    new_count = 0
    for stage, stage_name in STAGES:
        if new_count >= MAX_NEW_PER_ARTICLE:
            break
        ids, titles = search_ids(law, stage, f"{date_from:%d.%m.%Y}", f"{date_to:%d.%m.%Y}")
        fresh = [i for i in ids if i not in seen]
        print(f"  {stage_name}: найдено {len(ids)}, новых {len(fresh)}")
        for did in fresh:
            if new_count >= MAX_NEW_PER_ARTICLE:
                break
            try:
                title, court, text = fetch_doc_text(did)
            except Exception as e:
                print(f"  doc FAIL {did}: {e}")
                continue
            if len(text) < 500:
                seen.add(did)
                continue
            dm = re.search(r"от (\d+) (\S+) (\d{4})", title)
            months = {"января": "01", "февраля": "02", "марта": "03", "апреля": "04",
                      "мая": "05", "июня": "06", "июля": "07", "августа": "08",
                      "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12"}
            date_tag = f"{dm.group(3)}-{months.get(dm.group(2), '00')}-{int(dm.group(1)):02d}" if dm else "0000-00-00"
            with open(os.path.join(cases_dir, f"{date_tag}_{did}.txt"), "w", encoding="utf-8") as f:
                f.write(f"# {title}\n{stage_name}\n{court}\n{BASE}/regular/doc/{did}/\n\n{text}\n")
            seen.add(did)
            new_count += 1
            time.sleep(SLEEP)
    with open(seen_path, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(seen)))
    rebuild_digest(art_dir, term, law)
    print(f"  сохранено новых: {new_count}")


def main():
    if not os.path.exists(ARTICLES_FILE):
        print(f"нет {ARTICLES_FILE}")
        sys.exit(1)
    terms = [l.strip() for l in open(ARTICLES_FILE, encoding="utf-8")
             if l.strip() and not l.startswith("#")]
    print(f"{datetime.now():%Y-%m-%d %H:%M} статей: {len(terms)}")
    for t in terms:
        try:
            process_article(t)
        except Exception as e:
            print(f"== {t} FAIL: {e}")
        time.sleep(SLEEP)
    print("DONE")


if __name__ == "__main__":
    main()
