#!/usr/bin/env python3
"""Выгрузка всех федеральных таблиц stat.апи-пресс.рф (year=all) в CSV."""
import csv
import re
import time
import urllib.request
import urllib.parse
import http.cookiejar
import os

BASE = "https://stat.xn----7sbqk8achja.xn--p1ai"
import sys
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "knowledge", "sudstat")

TABLES = [
    ("ug", 11, 1,  "ug_obshchie_pokazateli_po_kategoriyam"),
    ("ug", 11, 16, "ug_tyazhest_prestupleniya"),
    ("ug", 12, 7,  "ug_osnovaniya_prekrashcheniya_dela"),
    ("ug", 12, 8,  "ug_osnovnye_i_dop_nakazaniya"),
    ("ug", 12, 10, "ug_osnovaniya_osvobozhdeniya_ot_nakazaniya"),
    ("ug", 12, 11, "ug_kontingent_osuzhdennyh"),
    ("ug", 12, 12, "ug_osobennosti_soversheniya"),
    ("ug", 13, 14, "ug_mery_presecheniya"),
    ("ug", 15, 13, "ug_hodataystva_pri_sledstvii"),
    ("gr", 21, 0,  "gr_obshchie_pokazateli_po_kategoriyam"),
    ("gr", 22, 0,  "gr_otdelnye_kategorii_del"),
    ("gr", 23, 0,  "gr_istcy_i_otvetchiki"),
    ("adm1", 71, 0, "adm1_obshchie_pokazateli"),
    ("adm1", 72, 1, "adm1_otdelnye_kategorii_del"),
    ("adm1", 73, 0, "adm1_kategorii_istcov"),
    ("adm1", 74, 0, "adm1_kategorii_otvetchikov"),
    ("adm", 31, 1, "koap_otdelnye_pravonarusheniya"),
    ("adm", 32, 0, "koap_mery_obespecheniya"),
    ("adm", 34, 0, "koap_kategorii_pravonarushiteley"),
    ("arb", 41, 1, "arb_otdelnye_kategorii_del"),
    ("arb", 42, 1, "arb_obshchie_pokazateli"),
]

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
opener.addheaders = [("User-Agent", "Mozilla/5.0 (research; contact via site form)")]


def get(url):
    with opener.open(url, timeout=120) as r:
        return r.read().decode("utf-8", "replace")


def post(url, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        with opener.open(req, timeout=120) as r:
            r.read()
    except urllib.error.HTTPError as e:
        if e.code not in (302, 405):
            raise


def norm(label: str) -> str:
    s = label.replace("УК РФ", "").strip()
    if s.startswith("Всего"):
        return "ВСЕГО"
    s = re.sub(r"^Статья\s+", "", s)
    s = re.sub(r"\s*(часть|ч\.)\s*", " ч.", s)
    s = re.sub(r"\s*(пункт|п\.)\s*", " п.", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_rows(html):
    header, out = None, []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>", "", c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        cells = [re.sub(r"\s+", " ", c).replace("\xa0", " ").strip() for c in cells]
        if not cells:
            continue
        if cells[0] == "Год":
            header = cells
            continue
        if header and len(cells) == len(header):
            cells = [c.replace(" ", "") if i >= 2 else c for i, c in enumerate(cells)]
            out.append(cells)
    return header, out


os.makedirs(OUT, exist_ok=True)
titles = {}
for realm, t, s, slug in TABLES:
    url = f"{BASE}/stats/{realm}/t/{t}/s/{s}"
    try:
        get(url)  # init session
        post(f"{BASE}/filter", {
            "form[year]": "all", "form[realm]": realm,
            "form[table]": str(t), "form[stat]": str(s), "go": "фильтр",
        })
        html = get(url)
        header, rows = parse_rows(html)
        if not header or not rows:
            print(f"SKIP {slug}: no table (header={bool(header)})")
            continue
        m = re.search(r"<h4[^>]*>([^<]+)</h4>|<title>([^<]+)</title>", html)
        years = sorted(set(r[0] for r in rows))
        path = f"{OUT}/{slug}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([header[0], "Метка_норм"] + header[1:])
            w.writerows([[r[0], norm(r[1])] + r[1:] for r in rows])
        titles[slug] = (len(rows), years[0] + "-" + years[-1], header[1:4])
        print(f"OK {slug}: {len(rows)} rows, {years[0]}-{years[-1]}, {os.path.getsize(path)//1024} KB")
    except Exception as e:
        print(f"FAIL {slug}: {type(e).__name__}: {e}")
    time.sleep(1.5)

print("\nDONE", len(titles), "tables")
