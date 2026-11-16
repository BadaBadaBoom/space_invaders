"""NASA news stories for the game-over screen.

The listing at ``www.nasa.gov/news/recently-published/`` is fetched on a
worker thread while a game is being played, so the game-over screen never
waits on the network.  Stories are served in page order; when a page runs out
the feed follows the same "Next" link the site's pagination button uses and
carries on with the following page.

Nothing here is allowed to take the game down: a missing network, a broken
page or an undecodable image simply leaves the story card empty.
"""

from __future__ import annotations

import html as html_module
import io
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

import pygame

from config import NEWS_TIMEOUT, NEWS_URL, STORY_IMAGE_H, STORY_IMAGE_W

_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120 Safari/537.36")

_REST_FALLBACK = "https://www.nasa.gov/wp-json/nasa-hds/v1/content-lists"
_POST_TYPES = "post,nasa-blog,feature,press-release,image-article,podcast"

# Text that only ever comes from a page's navigation/chrome, never from a
# story summary.  science.nasa.gov's APOD cards currently leak their whole
# site menu into the excerpt, so those fall back to the article page.
_JUNK = re.compile(
    r"(APOD Archive Submissions|Archive Submissions Index Search Calendar|"
    r"Education About Discuss APOD|Suggested Searches)", re.IGNORECASE)


@dataclass
class Story:
    """One NASA item: what the game-over card needs and nothing more."""

    title: str
    summary: str
    link: str
    image_url: str
    kind: str = ""
    read_time: str = ""
    image: pygame.Surface | None = field(default=None, repr=False,
                                         compare=False)
    image_data: bytes | None = field(default=None, repr=False, compare=False)


@dataclass
class Listing:
    """One page of the archive: its cards and the page after it."""

    page: int
    stories: list[Story]
    next_page: int | None


# --------------------------------------------------------------------------- #
# Page parsing (no network, unit-testable)
# --------------------------------------------------------------------------- #

def _text(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment or "")
    text = html_module.unescape(text).replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    # Inline links leave a space before the full stop ("infrared light .").
    return re.sub(r"\s+([,.;:!?])", r"\1", text)


def _trim(text: str, limit: int = 320) -> str:
    """Shorten to *limit* characters on a sentence or word boundary."""
    text = _text(text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for stop in (". ", "! ", "? "):
        at = cut.rfind(stop)
        if at >= limit * 0.45:
            return cut[:at + 1].strip()
    at = cut.rfind(" ")
    return cut[:at if at > 0 else limit].rstrip(" ,;:-") + "…"


def _is_junk(summary: str, title: str) -> bool:
    if not summary:
        return True
    if _JUNK.search(summary):
        return True
    return summary.lower().startswith(title[:60].lower())


def _image_variant(url: str) -> str:
    """Ask NASA's CDN for a card-sized image instead of the original."""
    url = html_module.unescape(url or "")
    if not url:
        return ""
    host = urllib.parse.urlparse(url).netloc.lower()
    if "nasa.gov" not in host:
        return url
    if re.search(r"[?&]w=\d+", url):
        return re.sub(r"([?&])w=\d+", r"\1w=600", url)
    return url + ("&w=600" if "?" in url else "?w=600")


def parse_items(markup: str) -> list[Story]:
    """Extract the ordered story cards from listing markup."""
    stories: list[Story] = []
    for chunk in re.split(r'<div class="hds-content-item">', markup)[1:]:
        title_m = re.search(
            r'class="hds-a11y-heading-22"[^>]*>(.*?)</div>', chunk, re.DOTALL)
        link_m = re.search(
            r'<a href="([^"]+)" class="hds-content-item-heading"', chunk)
        img_m = re.search(r'<img[^>]*?src="([^"]+)"', chunk)
        summary_m = re.search(
            r'<p class="margin-top-0 margin-bottom-1">(.*?)</p>', chunk, re.DOTALL)
        read_m = re.search(
            r'<div class="hds-content-item-readtime[^"]*"[^>]*>(.*?)</div>',
            chunk, re.DOTALL)
        kind_m = re.search(
            r'<div class="display-flex flex-align-center label[^"]*"[^>]*>.*?'
            r'<span>(.*?)</span>', chunk, re.DOTALL)
        if not (title_m and link_m):
            continue
        title = _text(title_m.group(1))
        link = html_module.unescape(link_m.group(1))
        if not title or not link:
            continue
        image_url = _image_variant(img_m.group(1)) if img_m else ""
        summary = _text(summary_m.group(1)) if summary_m else ""
        stories.append(Story(
            title=title, summary=_trim(summary), link=link,
            image_url=image_url,
            kind=_text(kind_m.group(1)) if kind_m else "",
            read_time=_text(read_m.group(1)) if read_m else ""))
    return stories


def next_page_number(markup: str) -> int | None:
    """The page the site's pagination "Next" button points at."""
    match = re.search(
        r'<a[^>]*data-page-number="(\d+)"[^>]*>\s*Next\s*</a>',
        markup, re.DOTALL | re.IGNORECASE)
    return int(match.group(1)) if match else None


def parse_listing(page: str) -> Listing:
    """Parse page 1 of the recently-published archive."""
    main = re.search(r"<main[^>]*>(.*?)</main>", page, re.DOTALL)
    body = main.group(1) if main else page
    return Listing(page=1, stories=parse_items(body),
                   next_page=next_page_number(page))


def parse_page_payload(payload: dict, page: int) -> Listing:
    """Parse the JSON body the pagination endpoint returns."""
    return Listing(page=page,
                   stories=parse_items(payload.get("html", "")),
                   next_page=next_page_number(payload.get("pagination", "")))


def read_endpoint(page: str) -> str:
    match = re.search(
        r'restEndpoint\s*=\s*\{\s*"endpoint"\s*:\s*"([^"]+)"', page)
    return html_module.unescape(match.group(1)) if match else _REST_FALLBACK


def read_block_attrs(page: str) -> dict[str, str]:
    match = re.search(
        r'<div[^>]*class="hds-content-items[^"]*"[^>]*>', page)
    if not match:
        return {}
    attrs = dict(re.findall(r'data-([\w-]+)="([^"]*)"', match.group(0)))
    return {key: html_module.unescape(value) for key, value in attrs.items()}


def page_url(endpoint: str, attrs: dict[str, str], page: int) -> str:
    """Rebuild the exact query the site's Next button sends."""
    params = {
        "postType": attrs.get("post-type", _POST_TYPES),
        "postId": attrs.get("post-id", ""),
        "maxPages": attrs.get("max-num-pages", ""),
        "perPage": attrs.get("per-page", ""),
        "categories": attrs.get("categories", ""),
        "newsTags": attrs.get("news-tags", ""),
        "layout": attrs.get("layout", "list"),
        "showThumbnails": attrs.get("show-thumbnails", "yes"),
        "showReadTime": attrs.get("show-readtime", "yes"),
        "showExcerpts": attrs.get("show-excerpts", "yes"),
        "showContentTypeTags": attrs.get("show-content-type-tags", "yes"),
        "pageClicked": str(page),
    }
    return endpoint + "?" + urllib.parse.urlencode(params)


def summary_from_article(page: str) -> str:
    """Best available one-paragraph summary from a story's own page."""
    for tag in re.findall(r"<meta[^>]+>", page, re.IGNORECASE):
        attrs = {k.lower(): v for k, v in
                 re.findall(r'([\w:-]+)=["\']([^"\']*)["\']', tag)}
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        if key in ("og:description", "description", "twitter:description"):
            text = _text(attrs.get("content", ""))
            if len(text) > 40 and not _JUNK.search(text):
                return _trim(text)

    # APOD puts its write-up in a paragraph that begins "Explanation:".
    explanation = re.search(r"Explanation:\s*(.*?)</p>", page, re.DOTALL | re.IGNORECASE)
    if explanation:
        text = _text(explanation.group(1))
        if len(text) > 40:
            return _trim(text)

    main = re.search(r"<main[^>]*>(.*?)</main>", page, re.DOTALL)
    body = main.group(1) if main else page
    for para in re.findall(r"<p[^>]*>(.*?)</p>", body, re.DOTALL):
        text = _text(para)
        if len(text) >= 80 and not _JUNK.search(text):
            return _trim(text)
    return ""


# --------------------------------------------------------------------------- #
# Network + image handling
# --------------------------------------------------------------------------- #

def _get(url: str, limit: int = 4_000_000) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": _UA,
                      "Accept": "text/html,application/xhtml+xml,image/*,*/*"})
    with urllib.request.urlopen(request, timeout=NEWS_TIMEOUT) as response:
        return response.read(limit)


def _cover(image: pygame.Surface) -> pygame.Surface:
    """Scale and centre-crop an image into the story card's box."""
    width, height = image.get_size()
    if not width or not height:
        return pygame.Surface((STORY_IMAGE_W, STORY_IMAGE_H))
    scale = max(STORY_IMAGE_W / width, STORY_IMAGE_H / height)
    new_w = max(1, round(width * scale))
    new_h = max(1, round(height * scale))
    scaled = pygame.transform.smoothscale(image, (new_w, new_h))
    card = pygame.Surface((STORY_IMAGE_W, STORY_IMAGE_H))
    card.blit(scaled, ((STORY_IMAGE_W - new_w) // 2,
                       (STORY_IMAGE_H - new_h) // 2))
    return card


def decode_image(data: bytes | None) -> pygame.Surface | None:
    if not data:
        return None
    try:
        image = pygame.image.load(io.BytesIO(data))
    except (pygame.error, OSError, ValueError):
        return None
    try:
        image = image.convert()
    except pygame.error:
        pass
    return _cover(image)


class NewsFeed:
    """Loads the next story in the background and hands it to the game.

    ``update()`` is called once a frame from the main loop; ``begin_round()``
    when a game starts; ``take()`` when it ends.  One page is fetched ahead so
    crossing a page boundary never waits, and the index only advances when a
    story was actually shown, so a failed fetch is retried next round.
    """

    #: how many stories before the end of a page to fetch the next page
    PREFETCH_MARGIN = 3

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = bool(enabled)
        self.stories: list[Story] = []
        self.index = 0
        self.page = 0
        self.next_page: int | None = None
        self.current: Story | None = None
        self._endpoint = _REST_FALLBACK
        self._attrs: dict[str, str] = {}
        self._loaded: dict[int, Story] = {}
        self._next_listing: Listing | None = None
        self._lock = threading.Lock()
        self._result: tuple | None = None
        self._busy = False
        self._armed = False
        self._retry_at = 0.0

    # -- public API -------------------------------------------------------- #

    def begin_round(self) -> None:
        """Arm the feed for a new game; the upcoming story loads now."""
        if not self.enabled:
            return
        self.current = None
        self._armed = True
        self._ensure_story()

    def update(self) -> None:
        """Consume finished work and keep the prefetches going."""
        if not self.enabled:
            return
        self._collect()
        if not self.stories and not self._busy and time.time() >= self._retry_at:
            self._start(self._fetch_page, 1)
            return
        if (self._armed and self.stories and not self._busy
                and time.time() >= self._retry_at
                and self.index < len(self.stories)
                and self.index not in self._loaded):
            self._start(self._fetch_story, self.index, self.stories[self.index])
            return
        self._prefetch_page()

    def take(self) -> Story | None:
        """The story for the game over that just happened, if it is ready."""
        story = self.current
        if story is not None:
            self.current = None
            self._armed = False
        return story

    def advance(self) -> None:
        """Move to the following story, crossing to the next page at the end."""
        if not self.stories:
            return
        if self.index + 1 < len(self.stories):
            self.index += 1
            return
        if self._next_listing is not None:
            self._apply_listing(self._next_listing)
            self._next_listing = None
        # No next page (end of the archive) or it has not arrived yet: stay
        # put.  The prefetch will swap the page in as soon as it lands.

    # -- worker plumbing --------------------------------------------------- #

    def _start(self, target, *args) -> None:
        self._busy = True
        threading.Thread(target=target, args=args, daemon=True).start()

    def _ensure_story(self) -> None:
        if not self._armed or self._busy or not self.stories:
            return
        if self.index >= len(self.stories):
            return
        if self.index in self._loaded:
            self.current = self._loaded[self.index]
            return
        if time.time() < self._retry_at:
            return
        self._start(self._fetch_story, self.index, self.stories[self.index])

    def _prefetch_page(self) -> None:
        if (not self.next_page or self._busy or self._next_listing is not None
                or time.time() < self._retry_at
                or self.index < len(self.stories) - self.PREFETCH_MARGIN):
            return
        self._start(self._fetch_page, self.next_page)

    def _apply_listing(self, listing: Listing) -> None:
        self.stories = listing.stories
        self.next_page = listing.next_page
        self.page = listing.page
        self.index = 0
        self._loaded.clear()
        self.current = None

    def _fetch_page(self, page: int) -> None:
        try:
            if page == 1:
                markup = _get(NEWS_URL).decode("utf-8", "replace")
                self._endpoint = read_endpoint(markup)
                self._attrs = read_block_attrs(markup)
                listing = parse_listing(markup)
            else:
                url = page_url(self._endpoint, self._attrs, page)
                payload = json.loads(_get(url).decode("utf-8", "replace"))
                listing = parse_page_payload(payload, page)
            result = ("page", page, listing)
        except Exception as exc:  # noqa: BLE001 - offline is not a crash
            result = ("page", page, exc)
        with self._lock:
            self._result = result

    def _fetch_story(self, index: int, story: Story) -> None:
        try:
            summary = story.summary
            if _is_junk(summary, story.title):
                page = _get(story.link).decode("utf-8", "replace")
                summary = summary_from_article(page) or ""
            image_data = None
            if story.image_url:
                try:
                    image_data = _get(story.image_url)
                except Exception:  # noqa: BLE001 - heading/summary still work
                    image_data = None
            loaded = Story(title=story.title, summary=_trim(summary),
                           link=story.link, image_url=story.image_url,
                           kind=story.kind, read_time=story.read_time,
                           image_data=image_data)
            result = ("story", index, loaded)
        except Exception as exc:  # noqa: BLE001 - offline is not a crash
            result = ("story", index, exc)
        with self._lock:
            self._result = result

    def _collect(self) -> None:
        with self._lock:
            result, self._result = self._result, None
        if result is None:
            return
        kind, index, payload = result
        self._busy = False
        if isinstance(payload, Exception):
            self._retry_at = time.time() + 15.0
            return
        if kind == "page":
            listing = payload
            if listing.page == 1 or listing.page == self.next_page:
                if not self.stories:
                    self._apply_listing(listing)
                    self._ensure_story()
                elif listing.page != self.page:
                    self._next_listing = listing
            return
        story = payload
        story.image = decode_image(story.image_data)
        story.image_data = None
        self._loaded[index] = story
        if index == self.index:
            self.current = story
