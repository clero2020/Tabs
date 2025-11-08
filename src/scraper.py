import urllib.parse
import urllib.request
import urllib.error
from html.parser import HTMLParser
import html
import re


class FreetarSearchParser(HTMLParser):
    """
    HTML parser to extract song search results from Freetar.

    Attributes:
        songs (list): List of dictionaries containing song info.
    """
    def __init__(self):
        super().__init__()
        self.in_tr = False
        self.in_td = False
        self.current_class = ""
        self.current_data = {}
        self.songs = []
        self.current_tag = ""

    def handle_starttag(self, tag, attrs):
        """
        Handle the start of an HTML tag.
        """
        attrs = dict(attrs)
        self.current_tag = tag

        if tag == "tr":
            self.in_tr = True
            self.current_data = {}

        elif tag == "td":
            self.in_td = True
            self.current_class = attrs.get("class", "")

            # Capture rating value if present
            if "rating" in self.current_class and "data-value" in attrs:
                self.current_data["rating"] = attrs["data-value"]

        elif tag == "a" and self.in_td:
            href = attrs.get("href", "")
            if "artist" in self.current_class:
                self.current_data["artist_url"] = href
            elif "song" in self.current_class:
                # Add base URL for completeness
                self.current_data["song_url"] = "https://freetar.habedieeh.re/" + href

    def handle_data(self, data):
        """
        Handle the text content inside HTML tags.
        """
        if not self.in_tr or not self.in_td:
            return

        text = data.strip()
        if not text:
            return

        if "artist" in self.current_class:
            self.current_data["artist"] = text
        elif "song" in self.current_class:
            self.current_data["song"] = text
        elif "type" in self.current_class:
            self.current_data["type"] = text
        elif "rating" in self.current_class:
            self.current_data["rating_full"] = text

    def handle_endtag(self, tag):
        """
        Handle the end of an HTML tag.
        """
        if tag == "td":
            self.in_td = False
            self.current_class = ""
        elif tag == "tr":
            if self.current_data:
                self.songs.append(self.current_data)
            self.in_tr = False


def extract_songs_from_html(html_content):
    """
    Extract songs from HTML content using FreetarSearchParser.

    Args:
        html_content (str): The HTML content of the search page.

    Returns:
        list: List of song dictionaries.
    """
    parser = FreetarSearchParser()
    parser.feed(html_content)
    return parser.songs


def fetch_freetar_results(song_name):
    """
    Fetch search results from Freetar for a given song name.

    Args:
        song_name (str): Name of the song to search for.

    Returns:
        list: List of song dictionaries.
    """
    query = urllib.parse.quote(song_name)
    url = f"https://freetar.habedieeh.re/search?search_term={query}"

    print("Fetching HTML page...")
    headers = {"User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req) as response:
            html_content = response.read().decode("utf-8")
    except urllib.error.URLError as e:
        print(f"Error fetching URL {url}: {e}")
        return []

    print("HTML page retrieved")
    songs = extract_songs_from_html(html_content)
    return songs


class FreetarTabsParser(HTMLParser):
    """
    Robust HTML parser for Freetar / Ultimate Guitar tabs.

    Preserves line breaks and spacing in chords and tablature.
    """
    def __init__(self):
        super().__init__()
        self.details = {
            "title": "N/A",
            "artist": "N/A",
            "tuning": "N/A",
            "difficulty": "N/A",
            "capo": "N/A",
            "type": "N/A",
            "original_url": "N/A",
            "tab_content": ""
        }
        self.in_h5 = False
        self.in_title_link = False
        self.tab_content_started = False
        self.ignore_data = False
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        """
        Handle the start of an HTML tag for tab parsing.
        """
        attrs = dict(attrs)

        # Start capturing tab content after <hr>
        if tag == "hr":
            self.tab_content_started = True

        # Ignore chord visuals
        if tag in ('div', 'script', 'table', 'tbody', 'tr', 'td', 'th'):
            if attrs.get("id") == "chordVisuals":
                self.ignore_data = True
            elif self.ignore_data:
                self.depth += 1

        if self.ignore_data:
            return

        # Artist and title
        if tag == "h5":
            self.in_h5 = True
        elif self.in_h5 and tag == "a" and self.details["artist"] == "N/A":
            self.in_title_link = True

        # Original URL
        elif tag == "a" and attrs.get("href", "").startswith("https://tabs.ultimate-guitar.com"):
            self.details["original_url"] = attrs["href"].replace("?no_redirect", "")

        # Tab type
        elif tag == "span":
            cls = attrs.get("class")
            if cls and "favorite" in cls:
                self.details["type"] = attrs.get("data-type", "N/A")

        # Tags that imply a line break
        if self.tab_content_started and tag in ("br", "p", "div", "tr"):
            self.details["tab_content"] += "\n"

    def handle_data(self, data):
        """
        Handle text content inside HTML tags.
        """
        if self.ignore_data:
            return

        text = html.unescape(data)
        if not text.strip() and not text.endswith("\n"):
            # Preserve actual spaces
            self.details["tab_content"] += text.replace("\xa0", "\xa0\xa0")
            return

        if self.in_title_link and self.details["artist"] == "N/A":
            self.details["artist"] = text.strip()
        elif self.in_h5 and self.details["artist"] != "N/A" and self.details["title"] == "N/A" and text not in ["-", self.details["artist"]]:
            self.details["title"] = text.replace('(ver 1)', '').strip()
        elif self.tab_content_started:
            self.details["tab_content"] += text

    def handle_endtag(self, tag):
        """
        Handle the end of an HTML tag.
        """
        if tag == "h5":
            self.in_h5 = False
        elif tag == "a":
            self.in_title_link = False

        if self.ignore_data and tag in ('div', 'script', 'input', 'table', 'tbody', 'tr', 'td', 'th'):
            if self.depth > 0:
                self.depth -= 1
            else:
                self.ignore_data = False

        # Add line break at the end of paragraph-like tags
        if self.tab_content_started and tag in ("p", "div", "br", "tr"):
            self.details["tab_content"] += "\n"

    def set_metadata_from_raw_html(self, raw_html):
        """
        Extract metadata like difficulty, capo, and tuning using regex from raw HTML.
        """
        difficulty_match = re.search(r'Difficulty: (.*?)<br>', raw_html)
        if difficulty_match:
            self.details["difficulty"] = difficulty_match.group(1).strip()

        capo_match = re.search(r'Capo: (.*?) </div>', raw_html)
        if capo_match:
            self.details["capo"] = capo_match.group(1).strip()

        tuning_match = re.search(r'Tuning: (.*?) \(Standard\)<br>', raw_html)
        if tuning_match:
            self.details["tuning"] = tuning_match.group(1).strip()

    def clean_tab_content(self):
        """
        Clean tab content:
        - Remove excessive empty lines at the start/end
        - Remove scripts and "Alternative versions" text
        - Normalize line breaks
        """
        content = self.details["tab_content"]

        # Remove scripts and "Alternative versions"
        content = re.sub(r"\$\(document\).*", "", content, flags=re.DOTALL)
        content = re.sub(r"Alternative versions.*", "", content, flags=re.DOTALL)

        # Clean up empty lines
        lines = content.splitlines()
        cleaned_lines = []

        for line in lines:
            l = line.rstrip()
            if l.strip() == "":
                if cleaned_lines and cleaned_lines[-1] != "":
                    cleaned_lines.append("")
            else:
                cleaned_lines.append(l)

        # Remove leading/trailing empty lines
        while cleaned_lines and cleaned_lines[0] == "":
            cleaned_lines.pop(0)
        while cleaned_lines and cleaned_lines[-1] == "":
            cleaned_lines.pop(-1)

        self.details["tab_content"] = "\n".join(cleaned_lines)


def get_song_details(url):
    """
    Download, parse, and clean song tab details from a URL.

    Args:
        url (str): URL of the song tab page.

    Returns:
        dict: Dictionary containing song metadata and tab content.
    """
    if not url:
        return {}

    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            html_content = response.read().decode("utf-8")
    except urllib.error.URLError as e:
        print(f"Error fetching URL {url}: {e}")
        return {}
    except Exception as e:
        print(f"Unexpected error: {e}")
        return {}

    parser = FreetarTabsParser()
    parser.feed(html_content)
    parser.set_metadata_from_raw_html(html_content)
    parser.clean_tab_content()
    return parser.details

