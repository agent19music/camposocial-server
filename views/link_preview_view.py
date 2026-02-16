"""
Link preview endpoint: fetch Open Graph metadata (or Spotify oEmbed) for a URL.
Used by the client to render rich link cards in yaps and community posts.
"""
from flask import Blueprint, request, jsonify
import requests
from urllib.parse import urlparse
from bs4 import BeautifulSoup

link_preview_bp = Blueprint("link_preview", __name__)

REQUEST_TIMEOUT = 4
USER_AGENT = "Mozilla/5.0 (compatible; CampoSocial/1.0; +https://camposocial.app)"


def _is_spotify_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        netloc = (parsed.netloc or "").lower()
        return "spotify.com" in netloc
    except Exception:
        return False


def _fetch_spotify_oembed(url: str) -> dict | None:
    """Fetch Spotify oEmbed JSON. Returns dict with html, title, etc. or None."""
    try:
        r = requests.get(
            "https://open.spotify.com/oembed",
            params={"url": url},
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        if r.status_code != 200:
            return None
        data = r.json()
        return {
            "type": "spotify",
            "url": url,
            "title": data.get("title") or "Spotify",
            "html": data.get("html"),
            "thumbnail_url": data.get("thumbnail_url"),
            "site_name": "Spotify",
        }
    except Exception:
        return None


def _fetch_og_metadata(url: str) -> dict | None:
    """Fetch page and parse Open Graph meta tags. Returns dict or None."""
    try:
        r = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        og = {}
        for attr in ("title", "description", "image", "site_name"):
            meta = soup.find("meta", property=f"og:{attr}")
            if meta and meta.get("content"):
                key = "image_url" if attr == "image" else attr
                og[key] = (meta.get("content") or "").strip()
        if not og:
            return None
        og.setdefault("title", "")
        og.setdefault("description", "")
        og.setdefault("image_url", "")
        og.setdefault("site_name", "")
        og["type"] = "og"
        og["url"] = url
        return og
    except Exception:
        return None


@link_preview_bp.route("/link-preview", methods=["GET"])
def get_link_preview():
    """GET /link-preview?url=... - returns Open Graph or Spotify preview data."""
    url = (request.args.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Missing url parameter"}), 400
    if not url.startswith("http://") and not url.startswith("https://"):
        return jsonify({"error": "Invalid url scheme"}), 400
    try:
        parsed = urlparse(url)
        if not parsed.netloc:
            return jsonify({"error": "Invalid url"}), 400
    except Exception:
        return jsonify({"error": "Invalid url"}), 400

    if _is_spotify_url(url):
        data = _fetch_spotify_oembed(url)
    else:
        data = _fetch_og_metadata(url)

    if not data:
        return jsonify({"error": "Could not fetch preview", "url": url}), 422
    return jsonify(data), 200
