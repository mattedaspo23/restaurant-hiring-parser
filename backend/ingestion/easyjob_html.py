import logging
from typing import List
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

EASYJOB_SEARCH_URL = "https://www.easyjob.it/offerte-di-lavoro/{role}"


def _playwright_fetch_listings(role: str) -> List[dict]:
    listings = []
    url = EASYJOB_SEARCH_URL.format(role=quote_plus(role))
    logger.info("Playwright fallback for EasyJob: %s", url)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            job_cards = page.query_selector_all(
                "div.job-listing, article.job-item, div.offer-card, li.job-result"
            )

            if not job_cards:
                job_cards = page.query_selector_all("div[class*='job'], div[class*='offer'], div[class*='listing']")

            for card in job_cards:
                title_el = card.query_selector("h2 a, h3 a, a.job-title, a[class*='title']")
                company_el = card.query_selector(
                    "span.company, div.company-name, span[class*='company']"
                )
                location_el = card.query_selector(
                    "span.location, div.job-location, span[class*='location']"
                )
                desc_el = card.query_selector(
                    "p.description, div.job-description, div[class*='snippet']"
                )

                title = title_el.inner_text().strip() if title_el else ""
                company = company_el.inner_text().strip() if company_el else ""
                location = location_el.inner_text().strip() if location_el else ""
                description = desc_el.inner_text().strip() if desc_el else ""
                link = title_el.get_attribute("href") if title_el else ""

                if link and not link.startswith("http"):
                    link = f"https://www.easyjob.it{link}"

                if title:
                    raw_text = f"{title}\n{company}\n{location}\n{description}"
                    listings.append(
                        {
                            "title": title,
                            "company": company,
                            "location": location,
                            "url": link,
                            "raw_text": raw_text,
                            "source": "easyjob",
                        }
                    )

            browser.close()
    except Exception as e:
        logger.error("EasyJob Playwright fallback failed: %s", e)

    return listings


def fetch_easyjob_listings(role: str = "ristorazione") -> List[dict]:
    url = EASYJOB_SEARCH_URL.format(role=quote_plus(role))
    logger.info("Fetching EasyJob listings: %s", url)

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
        }
        resp = requests.get(url, timeout=15, headers=headers)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        job_cards = soup.select(
            "div.job-listing, article.job-item, div.offer-card, li.job-result"
        )
        if not job_cards:
            job_cards = soup.find_all(
                "div", class_=lambda c: c and ("job" in c or "offer" in c or "listing" in c)
            )

        if not job_cards:
            logger.warning("No job cards found via BS4, falling back to Playwright")
            return _playwright_fetch_listings(role)

        listings = []
        for card in job_cards:
            title_tag = card.find(["h2", "h3"])
            title_link = title_tag.find("a") if title_tag else card.find("a", class_=lambda c: c and "title" in c)

            title = ""
            link = ""
            if title_link:
                title = title_link.get_text(strip=True)
                link = title_link.get("href", "")
            elif title_tag:
                title = title_tag.get_text(strip=True)

            if link and not link.startswith("http"):
                link = f"https://www.easyjob.it{link}"

            company_tag = card.find(
                ["span", "div"],
                class_=lambda c: c and ("company" in c if c else False),
            )
            company = company_tag.get_text(strip=True) if company_tag else ""

            location_tag = card.find(
                ["span", "div"],
                class_=lambda c: c and ("location" in c if c else False),
            )
            location = location_tag.get_text(strip=True) if location_tag else ""

            desc_tag = card.find(
                ["p", "div"],
                class_=lambda c: c and ("description" in c or "snippet" in c if c else False),
            )
            description = desc_tag.get_text(strip=True) if desc_tag else ""

            if not description:
                description = card.get_text(separator=" ", strip=True)

            if title:
                raw_text = f"{title}\n{company}\n{location}\n{description}"
                listings.append(
                    {
                        "title": title,
                        "company": company,
                        "location": location,
                        "url": link,
                        "raw_text": raw_text,
                        "source": "easyjob",
                    }
                )

        logger.info("Fetched %d EasyJob listings via HTML", len(listings))
        return listings if listings else _playwright_fetch_listings(role)

    except requests.RequestException as e:
        logger.error("EasyJob HTML fetch failed: %s — falling back to Playwright", e)
        return _playwright_fetch_listings(role)
