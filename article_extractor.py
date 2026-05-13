import requests
import trafilatura

from http_client import session

MAX_ARTICLE_LENGTH = 12000


def extract_article(url):

    try:

        response = session.get(
            url,
            timeout=20,
            headers={
                "User-Agent": (
                    "Mozilla/5.0"
                )
            }
        )

        if "text/html" not in response.headers.get(
            "Content-Type", ""
        ):
            return ""

        downloaded = response.text

        extracted = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False
        )

        if not extracted:
            return ""

        return extracted[:MAX_ARTICLE_LENGTH]

    except Exception:

        return ""