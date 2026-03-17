import logging
from typing import List
from urllib.parse import quote_plus

import feedparser
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

INDEED_RSS_URL = "https://it.indeed.com/rss?q={role}&l={location}"


def _fetch_description_text(url: str) -> str:
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        desc_div = soup.find("div", {"id": "jobDescriptionText"}) or soup.find(
            "div", class_="jobsearch-jobDescriptionText"
        )
        if desc_div:
            return desc_div.get_text(separator="\n", strip=True)
        body = soup.find("body")
        return body.get_text(separator="\n", strip=True) if body else resp.text
    except Exception as e:
        logger.warning("Failed to fetch description from %s: %s", url, e)
        return ""


def _playwright_fetch_listings(role: str, location: str) -> List[dict]:
    listings = []
    search_url = f"https://it.indeed.com/lavoro?q={quote_plus(role)}&l={quote_plus(location)}"
    logger.info("Playwright fallback: loading %s", search_url)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            job_cards = page.query_selector_all("div.job_seen_beacon, div.jobsearch-ResultsList > div")
            for card in job_cards:
                title_el = card.query_selector("h2.jobTitle a, a.jcs-JobTitle")
                company_el = card.query_selector("span[data-testid='company-name'], span.companyName")
                location_el = card.query_selector("div[data-testid='text-location'], div.companyLocation")
                snippet_el = card.query_selector("div.job-snippet, td.resultContent")

                title = title_el.inner_text().strip() if title_el else ""
                company = company_el.inner_text().strip() if company_el else ""
                loc = location_el.inner_text().strip() if location_el else ""
                snippet = snippet_el.inner_text().strip() if snippet_el else ""
                link = title_el.get_attribute("href") if title_el else ""

                if link and not link.startswith("http"):
                    link = f"https://it.indeed.com{link}"

                if title:
                    full_text = f"{title}\n{company}\n{loc}\n{snippet}"
                    if link:
                        desc = _fetch_description_text(link)
                        if desc:
                            full_text += f"\n{desc}"

                    listings.append(
                        {
                            "title": title,
                            "company": company,
                            "location": loc,
                            "url": link,
                            "raw_text": full_text,
                            "source": "indeed",
                        }
                    )

            browser.close()
    except Exception as e:
        logger.error("Playwright fallback failed: %s", e)

    return listings


def fetch_indeed_listings(
    role: str = "", location: str = "Italia"
) -> List[dict]:
    url = INDEED_RSS_URL.format(role=quote_plus(role), location=quote_plus(location))
    logger.info("Fetching Indeed RSS: %s", url)

    try:
        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            raise ValueError(f"Feed parse error: {feed.bozo_exception}")

        if not feed.entries:
            logger.warning("No RSS entries found, falling back to Playwright")
            return _playwright_fetch_listings(role, location)

        listings = []
        for entry in feed.entries:
            title = entry.get("title", "")
            link = entry.get("link", "")
            summary = entry.get("summary", "")
            published = entry.get("published", "")

            full_text = f"{title}\n{summary}"
            if link:
                description = _fetch_description_text(link)
                if description:
                    full_text += f"\n{description}"

            company = ""
            location_text = ""
            if " - " in title:
                parts = title.rsplit(" - ", 2)
                if len(parts) >= 2:
                    company = parts[-2].strip() if len(parts) == 3 else ""
                    location_text = parts[-1].strip()

            listings.append(
                {
                    "title": title,
                    "company": company,
                    "location": location_text,
                    "published": published,
                    "url": link,
                    "raw_text": full_text,
                    "source": "indeed",
                }
            )

        logger.info("Fetched %d Indeed listings via RSS", len(listings))
        return listings

    except Exception as e:
        logger.error("RSS fetch failed: %s — falling back to Playwright", e)
        return _playwright_fetch_listings(role, location)
