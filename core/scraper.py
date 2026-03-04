"""Two-pass conference exhibitor scraper with Playwright.

Strategy:
1. Open exhibitor list URL in headless browser
2. Sniff network requests to detect API endpoints
3. If API found → paginate through it (fast, reliable)
4. If no API → check for server-side pagination (?page=N)
5. If JS-rendered → use Playwright to click through pages
6. Collect company names + detail page URLs
7. Visit each detail page to extract rich data (website, LinkedIn, etc.)
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Awaitable
from urllib.parse import urljoin, urlparse

import httpx
from playwright.async_api import async_playwright, Page, BrowserContext, Route

logger = logging.getLogger(__name__)

# Type for progress callback: (stage, message, current, total)
ProgressCallback = Callable[[str, str, int, int], Awaitable[None]]


@dataclass
class ScrapedExhibitor:
    """Raw exhibitor data extracted from the conference site."""
    company_name: str
    detail_page_url: str = ""
    booth_location: str = ""
    categories: list[str] = field(default_factory=list)
    # Fields from detail page
    website_url: str = ""
    linkedin_url: str = ""
    contact_url: str = ""
    description: str = ""
    logo_url: str = ""


@dataclass
class DetectedAPI:
    """An API endpoint discovered via network sniffing."""
    url: str
    method: str = "GET"
    headers: dict = field(default_factory=dict)
    has_pagination: bool = False
    page_param: str = ""  # e.g. "page", "offset"
    sample_response: dict | list | None = None


async def _noop_progress(stage: str, msg: str, current: int, total: int) -> None:
    pass


class ConferenceScraper:
    """Scrapes conference exhibitor lists using a hybrid strategy."""

    def __init__(
        self,
        delay: float = 1.0,
        max_detail_pages: int = 1000,
        on_progress: ProgressCallback | None = None,
    ):
        self.delay = delay
        self.max_detail_pages = max_detail_pages
        self.on_progress = on_progress or _noop_progress
        self._api_requests: list[dict] = []

    async def scrape(self, url: str) -> list[ScrapedExhibitor]:
        """Full two-pass scrape: list pages → detail pages."""
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )

            try:
                # Pass 1: Scrape the list
                await self.on_progress("scrape_list", "Opening exhibitor list page...", 0, 0)
                exhibitors = await self._scrape_list(context, url)
                await self.on_progress(
                    "scrape_list",
                    f"Found {len(exhibitors)} exhibitors",
                    len(exhibitors),
                    len(exhibitors),
                )

                if not exhibitors:
                    return []

                # Pass 2: Scrape detail pages (skip if table extraction
                # already provided rich data — no detail pages to visit)
                detail_count = sum(1 for e in exhibitors if e.detail_page_url)
                if detail_count > 0:
                    await self.on_progress(
                        "scrape_details",
                        f"Scraping {detail_count} detail pages...",
                        0,
                        detail_count,
                    )
                    await self._scrape_details(context, exhibitors)

                return exhibitors

            finally:
                await context.close()
                await browser.close()

    async def _scrape_list(
        self, context: BrowserContext, url: str
    ) -> list[ScrapedExhibitor]:
        """Pass 1: Get all exhibitors from the list page(s)."""
        page = await context.new_page()
        self._api_requests = []

        # Intercept XHR/fetch requests to sniff APIs
        page.on("response", self._capture_api_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.warning("Page load timeout/error for %s: %s", url, e)
            try:
                await page.wait_for_timeout(5000)
            except Exception:
                pass

        # Wait for content to render (JS frameworks, lazy loading)
        await page.wait_for_timeout(5000)

        # Strategy 1: Check for API endpoint
        api = self._detect_api_endpoint(url)
        if api:
            logger.info("Detected API endpoint: %s", api.url)
            await self.on_progress("scrape_list", "Found API endpoint, fetching all pages...", 0, 0)
            exhibitors = await self._fetch_via_api(context, api, url)
            if exhibitors:
                await page.close()
                return exhibitors

        # Strategy 2: Extract from current page + handle pagination
        all_exhibitors = []
        page_text = await page.content()
        page_num = 1

        while True:
            await self.on_progress(
                "scrape_list", f"Extracting from page {page_num}...", page_num, 0
            )

            # Get text content + all links for LLM extraction
            page_data = await self._extract_page_data(page, url)
            all_exhibitors.append(page_data)

            # Try to find and click "next" button
            next_clicked = await self._click_next_page(page)
            if not next_clicked:
                break

            page_num += 1
            await page.wait_for_timeout(2000)

            if page_num > 100:  # Safety cap
                logger.warning("Hit page cap at %d pages", page_num)
                break

        await page.close()

        # Flatten and return raw page data for LLM extraction
        # The actual exhibitor extraction happens in the extractor module
        return self._merge_page_data(all_exhibitors)

    def _capture_api_response(self, response) -> None:
        """Capture API responses during page load for endpoint detection."""
        url = response.url
        content_type = response.headers.get("content-type", "")

        # Look for JSON API responses that might be exhibitor data
        if "json" in content_type and response.status == 200:
            parsed = urlparse(url)
            path = parsed.path.lower()

            # Common patterns for exhibitor/company list APIs
            keywords = [
                "exhibitor", "sponsor", "company", "partner",
                "vendor", "participant", "attendee", "brand",
                "search", "list", "directory", "catalog",
            ]
            if any(kw in path or kw in parsed.query.lower() for kw in keywords):
                self._api_requests.append({
                    "url": url,
                    "method": response.request.method,
                    "headers": dict(response.request.headers),
                    "path": path,
                    "query": parsed.query,
                })

    def _detect_api_endpoint(self, original_url: str) -> DetectedAPI | None:
        """Analyze captured requests to find the exhibitor list API."""
        if not self._api_requests:
            return None

        # Rank by relevance
        best = None
        best_score = 0

        for req in self._api_requests:
            score = 0
            path = req["path"]

            # Strong signals
            if "exhibitor" in path:
                score += 10
            if "sponsor" in path:
                score += 8
            if "company" in path or "companies" in path:
                score += 6
            if "directory" in path or "catalog" in path:
                score += 5

            # Pagination signals
            query = req.get("query", "")
            if any(p in query for p in ["page=", "offset=", "limit=", "skip="]):
                score += 3

            # GraphQL
            if "graphql" in path:
                score += 2

            if score > best_score:
                best_score = score
                page_param = ""
                for p in ["page", "offset", "skip", "cursor"]:
                    if f"{p}=" in query:
                        page_param = p
                        break

                best = DetectedAPI(
                    url=req["url"],
                    method=req["method"],
                    headers=req["headers"],
                    has_pagination=bool(page_param),
                    page_param=page_param,
                )

        return best if best_score >= 5 else None

    async def _fetch_via_api(
        self,
        context: BrowserContext,
        api: DetectedAPI,
        original_url: str,
    ) -> list[ScrapedExhibitor]:
        """Paginate through a detected API endpoint."""
        all_items = []
        page_num = 0
        base_url = urlparse(original_url)

        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                # Build paginated URL
                fetch_url = api.url
                if api.has_pagination and api.page_param:
                    sep = "&" if "?" in fetch_url else "?"
                    if api.page_param == "offset":
                        fetch_url = re.sub(
                            r"offset=\d+", f"offset={page_num * 50}", fetch_url
                        )
                    else:
                        fetch_url = re.sub(
                            rf"{api.page_param}=\d+",
                            f"{api.page_param}={page_num + 1}",
                            fetch_url,
                        )

                try:
                    # Forward cookies from the browser context
                    cookies = await context.cookies()
                    cookie_header = "; ".join(
                        f"{c['name']}={c['value']}" for c in cookies
                    )
                    headers = {
                        k: v for k, v in api.headers.items()
                        if k.lower() not in ("host", "content-length")
                    }
                    headers["cookie"] = cookie_header

                    resp = await client.get(fetch_url, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()

                except Exception as e:
                    logger.warning("API fetch failed for page %d: %s", page_num, e)
                    break

                # Extract items from response (handle various structures)
                items = self._extract_items_from_api(data)
                if not items:
                    break

                for item in items:
                    exhibitor = self._api_item_to_exhibitor(item, original_url)
                    if exhibitor:
                        all_items.append(exhibitor)

                await self.on_progress(
                    "scrape_list",
                    f"Fetched {len(all_items)} exhibitors via API...",
                    len(all_items), 0,
                )

                if not api.has_pagination:
                    break

                page_num += 1
                if page_num > 50:  # Safety cap
                    break

                await asyncio.sleep(0.5)

        return all_items

    def _extract_items_from_api(self, data: dict | list) -> list[dict]:
        """Extract array of items from various API response shapes."""
        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            # Common patterns: data.results, data.items, data.exhibitors, etc.
            for key in [
                "results", "items", "data", "exhibitors", "sponsors",
                "companies", "records", "entries", "hits", "nodes",
                "list", "content", "payload",
            ]:
                if key in data:
                    val = data[key]
                    if isinstance(val, list):
                        return val
                    if isinstance(val, dict) and "edges" in val:
                        # GraphQL pattern
                        return [e.get("node", e) for e in val["edges"]]

            # Nested data.data pattern
            if "data" in data and isinstance(data["data"], dict):
                return self._extract_items_from_api(data["data"])

        return []

    def _api_item_to_exhibitor(
        self, item: dict, base_url: str
    ) -> ScrapedExhibitor | None:
        """Convert an API response item to a ScrapedExhibitor."""
        # Try common name fields
        name = None
        for key in ["name", "company_name", "companyName", "title", "brand",
                     "exhibitor_name", "exhibitorName", "displayName"]:
            if key in item and item[key]:
                name = str(item[key]).strip()
                break

        if not name:
            return None

        # Detail page URL
        detail_url = ""
        for key in ["url", "link", "href", "slug", "permalink", "detailUrl",
                     "profileUrl", "page_url"]:
            if key in item and item[key]:
                detail_url = str(item[key])
                if not detail_url.startswith("http"):
                    detail_url = urljoin(base_url, detail_url)
                break

        # Website
        website = ""
        for key in ["website", "website_url", "websiteUrl", "homepage", "web"]:
            if key in item and item[key]:
                website = str(item[key])
                break

        # Description
        desc = ""
        for key in ["description", "summary", "about", "bio", "short_description",
                     "shortDescription", "excerpt"]:
            if key in item and item[key]:
                desc = str(item[key])[:500]
                break

        # Categories
        cats = []
        for key in ["categories", "tags", "sectors", "industry", "type"]:
            if key in item:
                val = item[key]
                if isinstance(val, list):
                    cats = [
                        str(v.get("name", v) if isinstance(v, dict) else v)
                        for v in val
                    ]
                elif isinstance(val, str):
                    cats = [val]
                break

        # Booth
        booth = ""
        for key in ["booth", "stand", "booth_number", "boothNumber", "location",
                     "standNumber"]:
            if key in item and item[key]:
                booth = str(item[key])
                break

        return ScrapedExhibitor(
            company_name=name,
            detail_page_url=detail_url,
            booth_location=booth,
            categories=cats,
            website_url=website,
            description=desc,
        )

    async def _extract_page_data(
        self, page: Page, base_url: str
    ) -> list[ScrapedExhibitor]:
        """Extract exhibitor data from the current page using DOM inspection.

        Tries multiple strategies in order:
        1. Table-based extraction (GDC-style: tables with Company/Booth columns
           and expandable rows containing description + website)
        2. Card/list CSS patterns (MWC-style: repeating card elements)
        3. Link-based extraction (fallback: links pointing to detail pages)
        """
        # Strategy 1: Table-based extraction
        table_exhibitors = await self._extract_from_tables(page, base_url)
        if table_exhibitors:
            return table_exhibitors

        exhibitors = []

        # Strategy 2: look for repeating card/list patterns
        selectors = [
            "[class*='exhibitor']", "[class*='sponsor']", "[class*='company']",
            "[class*='vendor']", "[class*='partner']", "[class*='brand']",
            "[data-type='exhibitor']", "[data-type='company']",
            ".exhibitor-card", ".company-card", ".exhibitor-item",
            ".directory-item", ".catalog-item",
        ]

        for selector in selectors:
            try:
                elements = await page.query_selector_all(selector)
                if len(elements) >= 3:  # Found a meaningful pattern
                    for el in elements:
                        name = await self._get_element_text(el)
                        link = await self._get_element_link(el, base_url)
                        if name and len(name) > 1 and len(name) < 200:
                            exhibitors.append(ScrapedExhibitor(
                                company_name=name.strip(),
                                detail_page_url=link,
                            ))
                    if exhibitors:
                        return exhibitors
            except Exception:
                continue

        # Strategy 3: look for links that point to exhibitor detail pages
        all_links = await page.query_selector_all("a[href]")
        seen_names = set()

        for link_el in all_links:
            try:
                href = await link_el.get_attribute("href") or ""
                full_url = urljoin(base_url, href)
                text = (await link_el.inner_text()).strip()

                # Skip navigation, empty, or very long text
                if not text or len(text) < 2 or len(text) > 200:
                    continue
                if text.lower() in ("next", "previous", "back", "home", "menu",
                                     "login", "sign in", "register", "search"):
                    continue

                # Check if this looks like a detail page link
                path = urlparse(full_url).path.lower()
                detail_signals = [
                    "exhibitor", "sponsor", "company", "partner",
                    "vendor", "profile", "brand", "participant",
                ]
                if any(s in path for s in detail_signals):
                    name = text.split("\n")[0].strip()
                    if name and name not in seen_names:
                        seen_names.add(name)
                        exhibitors.append(ScrapedExhibitor(
                            company_name=name,
                            detail_page_url=full_url,
                        ))
            except Exception:
                continue

        return exhibitors

    async def _extract_from_tables(
        self, page: Page, base_url: str
    ) -> list[ScrapedExhibitor]:
        """Extract exhibitors from HTML tables with Company/Booth columns.

        Handles pages like GDC where all exhibitor data (name, booth,
        description, website, social links) is embedded in table rows
        with expandable content — no detail pages needed.
        """
        result = await page.evaluate("""() => {
            const tables = document.querySelectorAll('table');
            const exhibitors = [];

            for (const table of tables) {
                // Check if this table has Company/Booth-style headers
                const headers = Array.from(table.querySelectorAll('th'))
                    .map(h => h.textContent.trim().toLowerCase());
                const hasCompanyCol = headers.some(
                    h => h.includes('company') || h.includes('exhibitor')
                       || h.includes('name')
                );
                if (!hasCompanyCol) continue;

                const rows = table.querySelectorAll('tbody tr');
                for (const row of rows) {
                    const cells = row.querySelectorAll('td');
                    if (cells.length < 1) continue;

                    const mainCell = cells[0];

                    // Company name: look for span.company-name or
                    // strong/heading text
                    let name = '';
                    const nameEl = mainCell.querySelector(
                        'span.company-name, [class*="company-name"]'
                    );
                    if (nameEl) {
                        name = nameEl.textContent.trim();
                    } else {
                        // Fallback: first strong or heading
                        const strong = mainCell.querySelector('strong, h2, h3, h4');
                        if (strong) {
                            name = strong.textContent.trim();
                        }
                    }
                    if (!name || name.length < 2) continue;

                    // Booth: second cell if it exists
                    let booth = '';
                    if (cells.length >= 2) {
                        booth = cells[1].textContent.trim();
                    }

                    // Links: extract website, linkedin, social
                    const links = mainCell.querySelectorAll('a[href]');
                    let website = '';
                    let linkedin = '';
                    let description = '';
                    let websiteFallback = '';

                    // Look for hidden expandable div (GDC pattern:
                    // <div id="id-..." style="display:none">content</div>)
                    const hiddenDiv = mainCell.querySelector(
                        'div[style*="display"], div[id^="id-"]'
                    );

                    // Check for explicit "Website" label in the expandable area
                    // GDC pattern: <strong>Website</strong><br><a href="url">
                    const searchScope = hiddenDiv || mainCell;
                    const strongs = searchScope.querySelectorAll('strong');
                    for (const s of strongs) {
                        if (s.textContent.trim().toLowerCase() === 'website') {
                            let sibling = s.nextElementSibling;
                            while (sibling) {
                                if (sibling.tagName === 'A') {
                                    const href = sibling.getAttribute('href');
                                    if (href && href.startsWith('http')) {
                                        website = href;
                                    }
                                    break;
                                }
                                sibling = sibling.nextElementSibling;
                            }
                            break;
                        }
                    }

                    for (const a of links) {
                        const href = a.getAttribute('href') || '';
                        if (!href.startsWith('http')) continue;

                        const domain = (() => {
                            try { return new URL(href).hostname.toLowerCase(); }
                            catch(e) { return ''; }
                        })();

                        const linkText = (a.textContent || '').trim();

                        // LinkedIn
                        if (domain.includes('linkedin.com')) {
                            if (!linkedin) linkedin = href;
                            continue;
                        }

                        // Social media (skip for website candidates)
                        const socialDomains = [
                            'twitter.com', 'x.com', 'facebook.com',
                            'instagram.com', 'youtube.com', 'tiktok.com',
                            'bsky.app', 'threads.net', 'mastodon.social',
                        ];
                        if (socialDomains.some(d => domain.includes(d))) {
                            continue;
                        }

                        // Skip # links (expand toggles)
                        if (href === '#' || href.startsWith('#')) continue;

                        // Track first external link as fallback website
                        if (!websiteFallback && linkText) {
                            websiteFallback = href;
                        }
                    }

                    // Use fallback if no explicit Website label found
                    if (!website && websiteFallback) {
                        website = websiteFallback;
                    }

                    // Description: extract from hidden div's textContent
                    // textContent includes hidden text but doesn't add
                    // newlines for <br> — so we use innerHTML-based parsing
                    if (hiddenDiv) {
                        // Get innerHTML, split on <br> and tags to get lines
                        const html = hiddenDiv.innerHTML;
                        // Remove all HTML tags and split on <br>, </p>, etc.
                        const rawText = html
                            .replace(/<br\\s*\\/?>/gi, '\\n')
                            .replace(/<\\/?(p|div|li|h[1-6])[^>]*>/gi, '\\n')
                            .replace(/<[^>]+>/g, '')
                            .replace(/&amp;/g, '&')
                            .replace(/&lt;/g, '<')
                            .replace(/&gt;/g, '>')
                            .replace(/&nbsp;/g, ' ')
                            .replace(/&#?\\w+;/g, '');
                        const lines = rawText.split('\\n')
                            .map(l => l.trim())
                            .filter(l => l.length > 0);
                        const descParts = [];
                        for (const line of lines) {
                            const ll = line.toLowerCase();
                            // Stop at "Website" label
                            if (ll === 'website'
                                || ll.startsWith('website')) break;
                            // Stop at URL-like text
                            if (line.match(/^(https?:|www\\.)/i)) break;
                            // Skip domain-like short text
                            if (line.match(/^[a-z0-9-]+\\.[a-z]{2,}/i)
                                && line.length < 60) break;
                            // Skip booth duplicates
                            if (booth && line === booth) continue;
                            // Skip empty-ish lines
                            if (line.length < 3) continue;
                            descParts.push(line);
                        }
                        description = descParts.join(' ').trim();
                        if (description.length > 500) {
                            description = description.substring(0, 500);
                        }
                    }

                    exhibitors.push({
                        name, booth, website, linkedin, description,
                    });
                }
            }
            return exhibitors;
        }""")

        if not result or len(result) < 3:
            return []

        logger.info("Table extraction found %d exhibitors", len(result))

        exhibitors = []
        seen = set()
        for item in result:
            name = item.get("name", "").strip()
            key = name.lower()
            if not name or key in seen:
                continue
            seen.add(key)
            exhibitors.append(ScrapedExhibitor(
                company_name=name,
                booth_location=item.get("booth", ""),
                website_url=item.get("website", ""),
                linkedin_url=item.get("linkedin", ""),
                description=item.get("description", ""),
            ))

        return exhibitors

    async def _get_element_text(self, element) -> str:
        """Get the primary text from an exhibitor card element."""
        # Try heading first
        for tag in ["h2", "h3", "h4", "h5", "strong", "b", "[class*='name']",
                     "[class*='title']"]:
            try:
                heading = await element.query_selector(tag)
                if heading:
                    text = (await heading.inner_text()).strip()
                    if text:
                        return text
            except Exception:
                continue

        # Fall back to first line of text
        try:
            text = (await element.inner_text()).strip()
            return text.split("\n")[0].strip()
        except Exception:
            return ""

    async def _get_element_link(self, element, base_url: str) -> str:
        """Get the detail page link from an exhibitor card."""
        try:
            # Check if element itself is a link
            href = await element.get_attribute("href")
            if href:
                return urljoin(base_url, href)

            # Look for a link inside
            link = await element.query_selector("a[href]")
            if link:
                href = await link.get_attribute("href")
                if href:
                    return urljoin(base_url, href)
        except Exception:
            pass
        return ""

    async def _click_next_page(self, page: Page) -> bool:
        """Try to find and click a 'next page' button. Returns True if successful."""
        # Common next-button selectors
        next_selectors = [
            "a[aria-label='Next']", "a[aria-label='next']",
            "button[aria-label='Next']", "button[aria-label='next']",
            "[class*='next']", "[class*='Next']",
            "a:has-text('Next')", "button:has-text('Next')",
            "a:has-text('>')", "button:has-text('>')",
            ".pagination a:last-child",
            "[class*='pagination'] a:last-child",
            "[class*='pager'] a:last-child",
        ]

        for selector in next_selectors:
            try:
                button = await page.query_selector(selector)
                if button:
                    is_disabled = await button.get_attribute("disabled")
                    classes = (await button.get_attribute("class")) or ""
                    if is_disabled or "disabled" in classes:
                        return False

                    await button.click()
                    await page.wait_for_timeout(2000)
                    return True
            except Exception:
                continue

        return False

    async def _scrape_details(
        self,
        context: BrowserContext,
        exhibitors: list[ScrapedExhibitor],
    ) -> None:
        """Pass 2: Visit detail pages and extract rich info."""
        detail_exhibitors = [e for e in exhibitors if e.detail_page_url]
        total = min(len(detail_exhibitors), self.max_detail_pages)
        page = await context.new_page()

        # Dismiss cookie/consent banners on the first page load
        # so they don't interfere with subsequent detail pages
        cookie_dismissed = False

        for i, exhibitor in enumerate(detail_exhibitors[:total]):
            try:
                await self.on_progress(
                    "scrape_details",
                    f"Scraping {exhibitor.company_name}...",
                    i + 1,
                    total,
                )

                await page.goto(
                    exhibitor.detail_page_url,
                    wait_until="domcontentloaded",
                    timeout=15000,
                )
                await page.wait_for_timeout(1500)

                # Dismiss cookie banner on first detail page visit
                if not cookie_dismissed:
                    try:
                        for btn_sel in [
                            "#onetrust-accept-btn-handler",
                            "#onetrust-reject-all-handler",
                            "button:has-text('Accept All')",
                            "button:has-text('Reject All')",
                        ]:
                            btn = await page.query_selector(btn_sel)
                            if btn and await btn.is_visible():
                                await btn.click()
                                await page.wait_for_timeout(500)
                                cookie_dismissed = True
                                break
                    except Exception:
                        pass
                    cookie_dismissed = True  # Don't retry on every page

                # Build list of conference-related domains to exclude
                detail_domain = urlparse(exhibitor.detail_page_url).netloc.lower()
                # Exclude the conference domain and common related domains
                conference_domains = {detail_domain}
                # Add parent domain (e.g. mwcbarcelona.com -> also block 4yfn.com)
                parts = detail_domain.split(".")
                if len(parts) >= 2:
                    base_domain = ".".join(parts[-2:])
                    conference_domains.add(base_domain)

                # Common conference platform domains to always exclude
                _platform_domains = [
                    "4yfn.com", "gsma.com", "gsmaadvance.com",
                    "swapcard.com", "grip.events",
                    "mapyourshow.com", "a2z.com", "jujama.com",
                    "eventbrite.com", "hopin.com", "brella.io",
                    "servicesshowcase.gsma.com", "membership.gsma.com",
                    # Common MWC sibling events
                    "mwcdoha.com", "mwckigali.com", "mwcshanghai.com",
                    "m360series.com", "novasummit.com",
                    "mobileworldlive.com",
                    # App stores
                    "apple.com", "play.google.com", "appgallery.huawei.com",
                    # Cookie/tracking
                    "onetrust.com",
                ]

                # Try to scope link extraction to the main content area
                # to avoid footer/header sponsor links — but only if the
                # container actually has links (some sites put content
                # outside <main>)
                link_scope = page
                for content_sel in [
                    "[class*='exhibitor']", "[class*='profile']",
                    "[class*='detail']", "article", "[role='main']",
                    "main",
                ]:
                    container = await page.query_selector(content_sel)
                    if container:
                        container_links = await container.query_selector_all("a[href]")
                        if len(container_links) >= 2:
                            link_scope = container
                            break

                # Extract links
                links = await link_scope.query_selector_all("a[href]")
                website_candidates = []

                for link_el in links:
                    try:
                        href = (await link_el.get_attribute("href")) or ""
                        href_lower = href.lower()
                        text = ((await link_el.inner_text()) or "").strip().lower()

                        if not href.startswith("http"):
                            continue

                        link_domain = urlparse(href).netloc.lower()

                        # Skip conference site and platform links
                        is_conference = any(
                            d in link_domain for d in conference_domains
                        )
                        is_platform = any(
                            d in link_domain for d in _platform_domains
                        )

                        # Social media domains (excluding LinkedIn which
                        # gets special handling below)
                        social_domains = [
                            "twitter.com", "x.com", "facebook.com",
                            "instagram.com", "youtube.com", "github.com",
                            "tiktok.com",
                        ]
                        is_social = any(d in link_domain for d in social_domains)
                        is_skip = is_conference or is_platform or is_social

                        # Website link — explicit text match (highest priority)
                        # Use startswith/in to handle "website\nwww.example.com"
                        text_first_line = text.split("\n")[0].strip()
                        if (text_first_line == "website"
                                or "visit website" in text
                                or "company website" in text
                                or "official site" in text
                                or "visit site" in text
                                or "go to website" in text):
                            if not is_conference and not is_platform:
                                exhibitor.website_url = href

                        # External link candidate (lower priority)
                        # Only consider links with visible text — empty-text
                        # links are typically sponsor/partner logo images
                        elif (not is_skip
                              and "linkedin.com" not in link_domain
                              and text.strip()):
                            website_candidates.append(href)

                        # LinkedIn — only company pages, not conference showcase
                        if "linkedin.com" in link_domain:
                            linkedin_path = urlparse(href).path.lower()
                            # Accept /company/ and /in/ links
                            # Reject /showcase/ links (conference pages)
                            if ("/company/" in linkedin_path
                                    or "/in/" in linkedin_path):
                                if not exhibitor.linkedin_url:
                                    exhibitor.linkedin_url = href

                        # Contact
                        if not exhibitor.contact_url:
                            if ("contact" in text or "mailto:" in href_lower
                                    or "contact" in href_lower):
                                exhibitor.contact_url = href

                    except Exception:
                        continue

                # Use first external link candidate if no explicit website found
                if not exhibitor.website_url and website_candidates:
                    exhibitor.website_url = website_candidates[0]

                # Extract description from page text
                if not exhibitor.description:
                    try:
                        # Strategy 1: CSS selectors for description containers
                        desc_selectors = [
                            "[class*='description']", "[class*='about']",
                            "[class*='summary']", "[class*='bio']",
                            ".profile-description",
                        ]
                        for sel in desc_selectors:
                            el = await page.query_selector(sel)
                            if el:
                                desc_text = (await el.inner_text()).strip()
                                if len(desc_text) > 20:
                                    exhibitor.description = desc_text[:500]
                                    break

                        # Strategy 2: Find the longest paragraph in <main>
                        # or in the page that mentions the company name
                        if not exhibitor.description:
                            company_first = exhibitor.company_name.split()[0].lower()
                            body_text = await page.evaluate("() => document.body.innerText")
                            best_para = ""
                            for para in body_text.split("\n"):
                                para = para.strip()
                                if len(para) < 30:
                                    continue
                                # Skip known boilerplate
                                if any(bp in para.lower() for bp in [
                                    "only at mwc", "cookie", "privacy",
                                    "partners & sponsors", "stay up to date",
                                    "buy a pass", "log in",
                                ]):
                                    continue
                                # Prefer paragraphs that mention the company
                                if company_first in para.lower():
                                    if len(para) > len(best_para):
                                        best_para = para
                                elif not best_para and len(para) > 50:
                                    best_para = para
                            if best_para:
                                exhibitor.description = best_para[:500]
                    except Exception:
                        pass

                # Extract logo
                if not exhibitor.logo_url:
                    try:
                        logo_selectors = [
                            "[class*='logo'] img", "[class*='brand'] img",
                            "img[class*='logo']", "img[alt*='logo']",
                            ".profile-image img", ".company-logo img",
                        ]
                        for sel in logo_selectors:
                            img = await page.query_selector(sel)
                            if img:
                                src = await img.get_attribute("src")
                                if src:
                                    exhibitor.logo_url = urljoin(
                                        exhibitor.detail_page_url, src
                                    )
                                    break
                    except Exception:
                        pass

            except Exception as e:
                logger.warning(
                    "Failed to scrape detail page for %s: %s",
                    exhibitor.company_name, e,
                )

            # Rate limiting
            await asyncio.sleep(self.delay)

        await page.close()

    def _merge_page_data(
        self, pages: list[list[ScrapedExhibitor]]
    ) -> list[ScrapedExhibitor]:
        """Deduplicate exhibitors across pages."""
        seen = {}
        for page_exhibitors in pages:
            for e in page_exhibitors:
                key = e.company_name.lower().strip()
                if key not in seen:
                    seen[key] = e
        return list(seen.values())
