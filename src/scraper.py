import urllib.parse
import urllib.request
from html.parser import HTMLParser
import re
import html

class FreetarSearchParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_tr = False
        self.in_td = False
        self.current_class = ""
        self.current_data = {}
        self.songs = []
        self.current_tag = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.current_tag = tag

        if tag == "tr":
            self.in_tr = True
            self.current_data = {}

        elif tag == "td":
            self.in_td = True
            self.current_class = attrs.get("class", "")

            if "rating" in self.current_class and "data-value" in attrs:
                self.current_data["rating"] = attrs["data-value"]

        elif tag == "a" and self.in_td:
            href = attrs.get("href", "")
            if "artist" in self.current_class:
                self.current_data["artist_url"] = href
            elif "song" in self.current_class:
                # Ajout de l'URL de base pour la complétude
                self.current_data["song_url"] = "https://freetar.habedieeh.re/" + href

    def handle_data(self, data):
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
        if tag == "td":
            self.in_td = False
            self.current_class = ""
        elif tag == "tr":
            if self.current_data:
                self.songs.append(self.current_data)
            self.in_tr = False


def extract_songs_from_html(html):
    parser = FreetarSearchParser()
    parser.feed(html)
    return parser.songs

def fetch_freetar_results(song_name):
    query = urllib.parse.quote(song_name)
    url = f"https://freetar.habedieeh.re/search?search_term={query}"

    print("récupération de la page html")
    headers = {"User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(url, headers=headers)

    with urllib.request.urlopen(req) as response:
        html = response.read().decode("utf-8")
    print("html de la recherche récupéré")
    songs = extract_songs_from_html(html)
    return songs

import re
from html.parser import HTMLParser
import urllib.request
import urllib.error # Pour une gestion d'erreur plus robuste

class FreetarTabsParser(HTMLParser):
    """
    Analyseur HTML robuste pour Freetar / Ultimate Guitar.
    Conserve les sauts de ligne et les espaces dans les accords.
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
        attrs = dict(attrs)

        # Commence à capturer après <hr>
        if tag == "hr":
            self.tab_content_started = True

        # Ignorer chordVisuals
        if tag in ('div', 'script', 'table', 'tbody', 'tr', 'td', 'th'):
            if attrs.get("id") == "chordVisuals":
                self.ignore_data = True
            elif self.ignore_data:
                self.depth += 1

        if self.ignore_data:
            return

        # artiste et titre
        if tag == "h5":
            self.in_h5 = True
        elif self.in_h5 and tag == "a" and self.details["artist"] == "N/A":
            self.in_title_link = True

        # URL
        elif tag == "a" and attrs.get("href", "").startswith("https://tabs.ultimate-guitar.com"):
            self.details["original_url"] = attrs["href"].replace("?no_redirect", "")

        # Type
        elif tag == "span":
            cls = attrs.get("class")
            if cls and "favorite" in cls:
                self.details["type"] = attrs.get("data-type", "N/A")

        # Les balises qui impliquent un saut de ligne
        if self.tab_content_started and tag in ("br", "p", "div", "tr"):
            self.details["tab_content"] += "\n"

    def handle_data(self, data):
        if self.ignore_data:
            return

        # décodage HTML (convertit &nbsp; → espace)
        text = html.unescape(data)
        if not text.strip() and not text.endswith("\n"):
            # conserve les vrais espaces
            self.details["tab_content"] += text
            return

        if self.in_title_link and self.details["artist"] == "N/A":
            self.details["artist"] = text.strip()

        elif self.in_h5 and self.details["artist"] != "N/A" and self.details["title"] == "N/A" and text not in ["-", self.details["artist"]]:
            self.details["title"] = text.replace('(ver 1)', '').strip()

        elif self.tab_content_started:
            # ne pas supprimer les espaces internes
            self.details["tab_content"] += text

    def handle_endtag(self, tag):
        if tag == "h5":
            self.in_h5 = False
        elif tag == "a":
            self.in_title_link = False

        if self.ignore_data and tag in ('div', 'script', 'input', 'table', 'tbody', 'tr', 'td', 'th'):
            if self.depth > 0:
                self.depth -= 1
            else:
                self.ignore_data = False

        # fin de paragraphe → saut de ligne
        if self.tab_content_started and tag in ("p", "div", "br", "tr"):
            self.details["tab_content"] += "\n"

    def set_metadata_from_raw_html(self, raw_html):
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
        Nettoie le contenu de tab_content :
        - Supprime les lignes vides excessives au début et à la fin
        - Retire les scripts et le texte 'Alternative versions' / jQuery
        - Normalise les sauts de ligne
        """
        content = self.details["tab_content"]

        # Supprimer les scripts et les "Alternative versions"
        content = re.sub(r"\$\(document\).*", "", content, flags=re.DOTALL)
        content = re.sub(r"Alternative versions.*", "", content, flags=re.DOTALL)

        # Nettoyer les lignes vides multiples
        lines = content.splitlines()
        cleaned_lines = []

        for line in lines:
            # Supprime les espaces superflus à droite/gauche
            l = line.rstrip()
            # Conserve les lignes non vides et évite les doubles vides
            if l.strip() == "":
                if cleaned_lines and cleaned_lines[-1] != "":
                    cleaned_lines.append("")
            else:
                cleaned_lines.append(l)

        # Supprime les vides en début/fin
        while cleaned_lines and cleaned_lines[0] == "":
            cleaned_lines.pop(0)
        while cleaned_lines and cleaned_lines[-1] == "":
            cleaned_lines.pop(-1)

        # Reconstruit le texte propre
        self.details["tab_content"] = "\n".join(cleaned_lines)

# --- FONCTION PRINCIPALE D'EXÉCUTION ---
def get_song_details(url):
    """
    Télécharge, analyse et nettoie les détails de la tablature à partir d'une URL.
    """
    if not url:
        return {}

    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8")
    except urllib.error.URLError as e:
        print(f"Erreur lors de la récupération de l'URL {url}: {e}")
        return {}
    except Exception as e:
        print(f"Une erreur inattendue s'est produite: {e}")
        return {}

    # 1. Parsing initial
    parser = FreetarTabsParser()
    parser.feed(html)

    # 2. Extraction des métadonnées par Regex (requiert le HTML brut)
    parser.set_metadata_from_raw_html(html)
    parser.clean_tab_content()

    return parser.details
