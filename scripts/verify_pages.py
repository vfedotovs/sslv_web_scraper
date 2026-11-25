#!/usr/bin/env python3
"""
Helper for Item 10 verification.
Compares live page count (using the same logic as the scraper) against expected.
"""
import sys
import requests
from bs4 import BeautifulSoup

def get_total_pages(bs_object, default=1):
    if not bs_object:
        return default
    page_nums = set()
    pager = bs_object.find("div", class_="td2")
    elems = pager.find_all(["a", "button"]) if pager else bs_object.find_all(["a", "button"])
    for el in elems:
        cls = " ".join(el.get("class", []))
        if "navi" in cls or "navia" in cls:
            t = el.get_text(strip=True)
            if t.isdigit():
                page_nums.add(int(t))
    return max(page_nums) if page_nums else default

def main(city: str, url: str):
    print(f"Fetching live page count for {city} ...")
    resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(resp.text, "html.parser")
    pages = get_total_pages(soup)
    print(f"{city}: live pages = {pages}")
    print("Use this number when comparing against a real /run-task run.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/verify_pages.py jurmala https://www.ss.lv/.../jurmala/sell/")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
