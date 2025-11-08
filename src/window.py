# window.py
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
import json, os, re
from gi.repository import Gtk, Adw, Pango, Gdk, GLib
# Assuming .scraper is correctly implemented
from .scraper import fetch_freetar_results, get_song_details

# Define the maximum size of the history stack
MAX_HISTORY_SIZE = 10
MAX_CACHED_SONGS = 1000
MAX_CACHED_SEARCHS = 1000

@Gtk.Template(resource_path='/org/clero/tabs/window.ui')
class TabsWindow(Adw.ApplicationWindow):
    __gtype_name__ = 'TabsWindow'

    # Template Children Bindings (assuming IDs are set in window.ui)
    search_entry = Gtk.Template.Child()
    results_list = Gtk.Template.Child()
    stack = Gtk.Template.Child()
    title_label = Gtk.Template.Child()
    artist_label = Gtk.Template.Child()
    details_label = Gtk.Template.Child()
    source_link = Gtk.Template.Child()
    lyrics_view = Gtk.Template.Child()
    search_box = Gtk.Template.Child()
    favorites_list = Gtk.Template.Child()
    back_button = Gtk.Template.Child()
    favorites_button = Gtk.Template.Child()
    fav_song_button = Gtk.Template.Child()
    fav_icon = Gtk.Template.Child()

    play_pause_button = Gtk.Template.Child()
    speed_scale = Gtk.Template.Child()
    chords_scrolled_window = Gtk.Template.Child()
    controls_box = Gtk.Template.Child()

    # NOUVELLES LIAISONS ADWLEAFLET
    leaflet = Gtk.Template.Child()
    chords_view_overlay = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # ========== STACK & LEAFLET ==========
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(400)
        # MODIFICATION: Connecter au leaflet au lieu du stack pour gérer la visibilité des contrôles
        self.leaflet.connect("notify::visible-child", self.on_leaflet_visible_child_changed)

        # ========== SEARCH CONNECTIONS ==========
        # Connect pressing Enter in the search entry
        self.search_entry.connect("activate", self.on_search_activated)
        # Connect clicking a song in the results list
        self.results_list.connect("row-activated", self.on_row_activated)
        # Connect clicking a song in the favorites list
        self.favorites_list.connect("row-activated", self.on_row_activated)

        # ========== SCROLL / PLAYBACK MANAGEMENT ==========
        self.scroll_timeout_id = None
        self.scroll_speed = 1.0       # Vitesse de base (du curseur)
        self.scroll_interval = 50     # Intervalle de mise à jour en ms
        self.scroll_amount = 0.5      # Pixels de base à défiler par intervalle

        # Connecter le bouton et le curseur (si les IDs existent dans le .ui)
        if self.play_pause_button:
            self.play_pause_button.connect("clicked", self.on_play_pause_clicked)
            self.play_pause_button.set_visible(False) # Caché par défaut

        if self.speed_scale:
            self.speed_scale.set_range(0.5, 5.0)
            self.speed_scale.set_value(self.scroll_speed)
            self.speed_scale.connect("value-changed", self.on_speed_scale_changed)
            self.speed_scale.set_visible(False) # Caché par défaut
        # ===================================================

        # ========== CONFIG FILE ==========
        self.cached_songs = None
        self.cached_searchs = None
        self.favorites = None

        # Define configuration file path
        self.config_dir = os.environ.get("XDG_CONFIG_HOME")
        self.config_file = os.path.join(self.config_dir, "config.json")

        # Set default zoom
        default_zoom = 10.0
        initial_zoom = default_zoom

        # Load configuration from file
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    loaded_size = float(config.get("zoom_size", default_zoom))
                    # Clamp zoom size between 6.0 and 36.0
                    initial_zoom = max(6.0, min(loaded_size, 36.0))
                    self.favorites = config.get("favorites")
                    self.cached_songs = config.get("cached_songs")
                    self.cached_searchs = config.get("cached_searchs")
            except (IOError, json.JSONDecodeError, ValueError) as e:
                print(f"Error loading config: {e}")
        else:
            print("no config file")

        # ========== CACHED SONGS ==========
        if not self.cached_songs :
            self.cached_songs = []
        if not self.cached_searchs :
            self.cached_searchs = []

        # ========== ZOOM MECHANISMS ==========
        self._current_zoom_size = initial_zoom
        self._pinch_start_size = initial_zoom

        # Apply loaded zoom size using CSS
        self.lyrics_view.add_css_class("zoomable-lyrics")
        self._lyrics_css_provider = Gtk.CssProvider()
        self.lyrics_view.get_style_context().add_provider(
            self._lyrics_css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.apply_zoom_change(0, initial_zoom)

        # Scroll zoom (Ctrl + Scroll)
        try:
            FlagsClass = Gtk.EventControllerScrollFlags
        except AttributeError:
            FlagsClass = Gdk.EventControllerScrollFlags

        scroll_controller = Gtk.EventControllerScroll.new(FlagsClass.VERTICAL)
        scroll_controller.connect("scroll", self.on_scroll_zoom)
        self.lyrics_view.add_controller(scroll_controller)

        # Pinch gesture zoom (for touch screens/touchpads)
        pinch_controller = Gtk.GestureZoom.new()
        pinch_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        pinch_controller.connect("begin", self.on_pinch_zoom_begin)
        pinch_controller.connect("scale-changed", self.on_pinch_zoom_changed)
        self.lyrics_view.add_controller(pinch_controller)

        # Key zoom (Ctrl + +/-)
        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", self.on_key_zoom)
        self.add_controller(key_controller)

        # Connect window close handler to save settings
        self.connect("close-request", self.on_close_request)

        # ========== LOAD FAVORITES ==========
        if self.favorites:
            for song in self.favorites:
                self._add_song_to_list(song, self.favorites_list)
        else:
            self.favorites = []
        self.songs_searched = self.favorites

        # favorites on song page
        self.fav_song_button.connect("clicked", self.on_fav_song_clicked)

        # ============ HISTORY MANAGEMENT ============
        # History stack (list of states, limited to MAX_HISTORY_SIZE)
        self.history = []
        # Initialize history with the starting state
        self._push_history(["favorites"])
        self.back_button.connect("clicked", self.on_back_clicked)
        self.favorites_button.connect("clicked", self.on_favorites_clicked)

        # ========== TEXT COLOR ==========
        self.lyrics_buffer = self.lyrics_view.get_buffer()

        # Get the tag table from the buffer
        tag_table = self.lyrics_buffer.get_tag_table()
        # Create a new tag for the color (e.g., green for chords)
        # We name it 'chord_tag'
        chord_tag = Gtk.TextTag.new("chord_tag")
        chord_tag.set_property("foreground", Adw.AccentColor.to_rgba(Adw.StyleManager.get_default().get_accent_color()).to_string())
        chord_tag.set_property("weight", Pango.Weight.BOLD)
        tag_table.add(chord_tag)

        # Create another tag (e.g., red for difficulty)
        difficulty_tag = Gtk.TextTag.new("difficulty_tag")
        difficulty_tag.set_property("foreground", "red")
        tag_table.add(difficulty_tag)

        # ========== NOUVEAU CSS POUR LA DIFFICULTÉ ET LE THÈME ==========
        # Créer un fournisseur de CSS pour les styles de l'application
        app_css_provider = Gtk.CssProvider()

        css_styles = """
        /* Ciblage des classes ajoutées dynamiquement au details_label */
        .difficulty-easy {
            color: @success_color; /* Utilise la couleur de succès du thème Adwaita (vert) */
            font-weight: bold;
        }

        .difficulty-medium {
            color: @warning_color; /* Utilise la couleur d'avertissement du thème Adwaita (orange/jaune) */
            font-weight: bold;
        }

        .difficulty-hard {
            color: @destructive_color; /* Utilise la couleur destructive du thème Adwaita (rouge) */
            font-weight: bold;
        }
        """
        app_css_provider.load_from_data(css_styles.encode())

        # Appliquer les styles au contexte de style de l'application
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            app_css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # ========== ANIMATION D'OPACITÉ ==========
        self.is_mouse_over_controls = False
        self.current_opacity = 1.0  # Commence à pleine opacité
        self.target_opacity = 1.0
        self.animation_speed = 0.1  # Vitesse de l'animation (plus grand = plus rapide)
        self.animation_timeout_id = None

        # Contrôleurs de souris pour gérer la transparence
        enter_controller = Gtk.EventControllerMotion.new()
        enter_controller.connect("enter", self.on_controls_enter)
        enter_controller.connect("leave", self.on_controls_leave)
        self.controls_box.add_controller(enter_controller)

        # Opacité initiale
        self.controls_box.set_opacity(1.0)

    # -----------------------
    # ANIMATION D'OPACITÉ
    # -----------------------
    def animate_opacity(self):
        """Animation fluide de l'opacité"""
        if abs(self.current_opacity - self.target_opacity) < 0.01:
            self.current_opacity = self.target_opacity
            self.controls_box.set_opacity(self.current_opacity)
            self.animation_timeout_id = None
            return False  # Arrêter l'animation

        # Interpolation linéaire
        self.current_opacity += (self.target_opacity - self.current_opacity) * self.animation_speed
        self.controls_box.set_opacity(self.current_opacity)
        return True  # Continuer l'animation

    def start_opacity_animation(self, target_opacity):
        """Démarre l'animation vers une opacité cible"""
        self.target_opacity = target_opacity

        # Démarrer l'animation si elle n'est pas déjà en cours
        if self.animation_timeout_id is None:
            # S'assurer que l'ancienne est supprimée si elle existe (pour éviter les doublons)
            if self.animation_timeout_id is not None:
                 GLib.source_remove(self.animation_timeout_id)
            self.animation_timeout_id = GLib.timeout_add(16, self.animate_opacity)  # ~60 FPS

    # -----------------------
    # SCROLL HANDLERS
    # -----------------------
    def on_speed_scale_changed(self, scale):
        """Met à jour la vitesse de défilement en fonction du curseur."""
        self.scroll_speed = scale.get_value()
        # Le pas de défilement est mis à jour automatiquement par self.scroll_speed dans _auto_scroll_step

    def start_scroll(self):
        """Démarre le défilement automatique."""
        if self.scroll_timeout_id is None and self.chords_scrolled_window:
            # Intervalle de mise à jour en ms.
            self.scroll_timeout_id = GLib.timeout_add(
                self.scroll_interval,
                self._auto_scroll_step
            )
            # Mettre à jour l'icône et la visibilité
            self.play_pause_button.set_icon_name("media-playback-pause-symbolic")
            self.speed_scale.set_visible(True)

            # Animation vers la transparence seulement si la souris n'est pas dessus
            if not self.is_mouse_over_controls:
                self.start_opacity_animation(0.3)

    def stop_scroll(self):
        """Arrête le défilement automatique."""
        if self.scroll_timeout_id is not None:
            GLib.source_remove(self.scroll_timeout_id)
            self.scroll_timeout_id = None
            # Mettre à jour l'icône et la visibilité
            self.play_pause_button.set_icon_name("media-playback-start-symbolic")
            self.speed_scale.set_visible(False)

            # Animation vers pleine opacité quand le défilement s'arrête
            self.start_opacity_animation(1.0)

    def _auto_scroll_step(self):
        """Effectue un petit pas de défilement."""
        if not self.chords_scrolled_window:
            return GLib.SOURCE_REMOVE

        adj = self.chords_scrolled_window.get_vadjustment()

        # Calculer le nouveau pas de défilement en fonction de la vitesse ajustée
        new_value = adj.get_value() + (self.scroll_amount * self.scroll_speed)

        # Upper est la hauteur totale du contenu, Page Size est la hauteur de la fenêtre visible
        max_value = adj.get_upper() - adj.get_page_size()

        if new_value >= max_value:
            # Atteint la fin : arrêter le défilement
            adj.set_value(max_value) # Assurer que nous sommes au fond
            self.stop_scroll()
            return GLib.SOURCE_REMOVE # Stopper la minuterie
        else:
            adj.set_value(new_value)
            return GLib.SOURCE_CONTINUE # Continuer la minuterie

    def on_play_pause_clicked(self, button):
        """Bascule entre lecture et pause."""
        # MODIFICATION: Vérifier l'enfant visible du leaflet
        if self.leaflet.get_visible_child() != self.chords_view_overlay:
            return

        if self.scroll_timeout_id is None:
            self.start_scroll()
        else:
            self.stop_scroll()

    def on_controls_enter(self, controller, x, y):
        """Quand la souris entre dans la zone des contrôles."""
        self.is_mouse_over_controls = True
        # Toujours passer à pleine opacité au survol
        self.start_opacity_animation(1.0)

    def on_controls_leave(self, controller):
        """Quand la souris quitte la zone des contrôles."""
        self.is_mouse_over_controls = False
        # Si le défilement est actif, retour à la transparence
        if self.scroll_timeout_id is not None:
            self.start_opacity_animation(0.3)
        # Sinon, rester à pleine opacité

    # -----------------------
    # HISTORY HELPERS
    # -----------------------
    def _push_history(self, new_state):
        """Adds a new state to the history stack and limits its size."""
        # Prevent stacking the same state repeatedly (e.g., clicking the same favorite button)
        if self.history and self.history[-1] == new_state:
            return

        self.history.append(new_state)
        # Limit the history size
        if len(self.history) > MAX_HISTORY_SIZE:
            # Remove the oldest state
            del self.history[0]

    def _get_current_state(self):
        """Returns the current state (last element in the stack)."""
        return self.history[-1] if self.history else ["favorites"]

    # -----------------------
    # UI HELPERS
    # -----------------------
    def _add_song_to_list(self, song, listbox):
        """Helper: add a song row to a given listbox."""
        # Grid container for song info
        main_grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        main_grid.set_margin_top(15)
        main_grid.set_margin_bottom(15)
        main_grid.set_margin_start(15)
        main_grid.set_margin_end(15)
        main_grid.set_size_request(2000, 500)

        # TITLE and ARTIST
        title_markup = f'<span size="large" weight="bold">{song["song"]}</span>'
        title_label = Gtk.Label(label="", xalign=0)
        title_label.set_markup(title_markup)
        main_grid.attach(title_label, 0, 0, 1, 1)

        artist_label = Gtk.Label(label=song.get('artist', 'N/A'), xalign=0)
        artist_label.add_css_class("body")
        main_grid.attach(artist_label, 0, 1, 1, 1)

        # TYPE and RATING aligned to the right
        type_label = Gtk.Label(label=f'Type: {song.get("type", "N/A")}', xalign=1)
        type_label.add_css_class("caption")
        main_grid.attach(type_label, 0, 1, 2, 1)

        rating_label = Gtk.Label(label=f'Rating: {song.get("rating_full", "0")}', xalign=0)
        rating_label.add_css_class("caption")
        main_grid.attach(rating_label, 0, 2, 1, 1)

        # Horizontal box: grid + spacer + button
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hbox.append(main_grid)

        # Card and ListBoxRow
        card_bin = Adw.Bin()
        card_bin.add_css_class("card")
        card_bin.set_child(hbox)

        row = Gtk.ListBoxRow()
        row.set_child(card_bin)
        row.url = song["song_url"]

        listbox.append(row)

    # -----------------------
    # NAVIGATION HANDLERS
    # -----------------------
    def on_search_activated(self, entry):
        text = entry.get_text()
        if text:
            songs = None
            for cached_search in self.cached_searchs:
                if cached_search[0] == text:
                    songs = cached_search[1]
                    break
            if not songs:
                songs = fetch_freetar_results(text)
                self.cached_searchs.append([text, songs])
                print("append")

            if len(self.cached_searchs) >= MAX_CACHED_SEARCHS:
                self.cached_searchs.pop(0)
                print("poped first cached search")

            # Clear previous results
            children_to_remove = list(self.results_list)
            for row in children_to_remove:
                 self.results_list.remove(row)

            for song in songs:
                self._add_song_to_list(song, self.results_list)

            # 1. Assurez-vous d'être dans le bon enfant du leaflet
            if self.leaflet.get_visible_child() == self.chords_view_overlay:
                 # Revenir sur le stack avant de changer la page du stack
                 self.leaflet.navigate(Adw.NavigationDirection.BACK)

            self.stack.set_visible_child_name("results")
            # Update history
            self._push_history(["search", songs])
            self.songs_searched = songs

    def on_row_activated(self, listbox, row):
        url = getattr(row, "url", None)
        song_data = None
        for cached_song in self.cached_songs:
            if cached_song[0] == url:
                song_data = cached_song[1]
                if cached_song[1] == {}:
                    self.cached_songs = [s for s in self.cached_songs if s[1] != {}]
                break
        if not song_data:
            song_data = get_song_details(url.replace("https://www", "https://tabs"))
            if song_data == {}:
                print("Connection error")
                return
            self.cached_songs.append([url, song_data])
            print("Song added to cache")

        # FIX DU BUG DE LA LIGNE 489: Utiliser la méthode correcte set_visible_child pour AdwLeaflet
        # C'est cette ligne qui résout l'AttributeError!
        self.leaflet.set_visible_child(self.chords_view_overlay)

        if len(self.cached_songs) >= MAX_CACHED_SONGS:
            self.cached_songs.pop(0)
            print("poped first cached song")

        # AFFICHER LES CONTRÔLES DE DÉFILEMENT
        self.play_pause_button.set_visible(True)
        self.speed_scale.set_visible(False)

        # Réinitialiser l'état du bouton play/pause
        self.stop_scroll()  # S'assurer que le défilement est arrêté
        self.play_pause_button.set_icon_name("media-playback-start-symbolic")

        # État initial - pleine opacité car pas de défilement
        self.current_opacity = 1.0
        self.target_opacity = 1.0
        self.controls_box.set_opacity(1.0)
        self.is_mouse_over_controls = False
        self.title_label.set_text(f"Title: {song_data['title']}")
        self.artist_label.set_text(f"Artist: {song_data['artist']}")
        difficulty = song_data['difficulty'].lower()
        # --- NOUVELLE LOGIQUE DE COULEUR DE DIFFICULTÉ ---
        # 1. Mise à jour du texte
        self.details_label.set_text(
            f"Tuning: {song_data['tuning']} — Capo: {song_data['capo']} — Difficulty: {song_data['difficulty']} — Type: {song_data['type']}"
        )

        # 2. Suppression de toutes les classes de difficulté précédentes
        self.details_label.remove_css_class("difficulty-easy")
        self.details_label.remove_css_class("difficulty-medium")
        self.details_label.remove_css_class("difficulty-hard")

        # 3. Application de la nouvelle classe CSS
        if 'easy' in difficulty or 'novice' in difficulty or 'beginner' in difficulty:
            self.details_label.add_css_class("difficulty-easy")
        elif 'medium' in difficulty or 'intermediate' in difficulty:
            self.details_label.add_css_class("difficulty-medium")
        elif 'hard' in difficulty or 'expert' in difficulty:
            self.details_label.add_css_class("difficulty-hard")
        # ----------------------------------------------------

        # --- SYNCHRONISER LE BOUTON DE FAVORIS ---
        for song in self.songs_searched:
            if url in song["song_url"]:
                self.current_song = song
                break
        is_favorite = self.current_song in self.favorites
        icon_name = "starred-symbolic" if is_favorite else "non-starred-symbolic"
        self.fav_icon.set_from_icon_name(icon_name)

        # ----------------------------------------
        self.source_link.set_uri(song_data['original_url'])
        self.source_link.set_label("View on Ultimate Guitar")

        # Application du texte et de la coloration (accords)
        self._set_lyrics_with_chord_colors(song_data['tab_content'])

        # Update history
        self._push_history(["song", song_data])

    def on_favorites_clicked(self, button):
        if self.leaflet.get_visible_child() == self.chords_view_overlay:
            self.leaflet.navigate(Adw.NavigationDirection.BACK)
        # Update history
        self._push_history(["favorites"])

        self.stack.set_visible_child_name("favorites")
        if self.favorites:
            # Reload the favorites list
            for child in list(self.favorites_list):
                self.favorites_list.remove(child)
            for song in self.favorites:
                self._add_song_to_list(song, self.favorites_list)

    def on_back_clicked(self, button):
        """Action for the back button, navigating through history."""
        # History must contain at least one state (the current one) and one previous state to go back to.
        if len(self.history) <= 1:
            return

        # 1. Remove the current state from the history stack
        current_state = self.history.pop()

        # 2. Get the new current state (the destination)
        destination_state = self._get_current_state()
        state_type = destination_state[0]

        # 3. Render the destination state
        if state_type == "favorites":
            # MODIFICATION: Naviguer le leaflet en arrière (au cas où)
            self.leaflet.navigate(Adw.NavigationDirection.BACK)
            self.stack.set_visible_child_name("favorites")
            # Reload favorites list (in case a favorite was added/removed on the song page)
            for child in list(self.favorites_list):
                self.favorites_list.remove(child)
            for song in self.favorites:
                self._add_song_to_list(song, self.favorites_list)

        elif state_type == "search":
            # MODIFICATION: Naviguer le leaflet en arrière (au cas où)
            self.leaflet.navigate(Adw.NavigationDirection.BACK)
            songs = destination_state[1]
            self.stack.set_visible_child_name("results")

            # Reload previous search results
            children_to_remove = list(self.results_list)
            for row in children_to_remove:
                 self.results_list.remove(row)
            for song in songs:
                self._add_song_to_list(song, self.results_list)

        elif state_type == "song":
            # MODIFICATION: Naviguer le leaflet vers la page des accords
            song_data = destination_state[1]
            self.leaflet.set_visible_child(self.chords_view_overlay) # La méthode est set_visible_child
            self.title_label.set_text(f"Title: {song_data['title']}")
            self.artist_label.set_text(f"Artist: {song_data['artist']}")
            self.details_label.set_text(
                f"Tuning: {song_data['tuning']} — Capo: {song_data['capo']} — Difficulty: {song_data['difficulty']} — Type: {song_data['type']}"
            )
            self.source_link.set_uri(song_data['original_url'])
            self.source_link.set_label("View on Ultimate Guitar")

            buffer = self.lyrics_view.get_buffer()
            buffer.set_text(song_data['tab_content'])


    # -----------------------
    # ZOOM MANAGEMENT
    # -----------------------
    def on_scroll_zoom(self, controller, dx, dy):
        """Handle zoom with Ctrl + Mouse Scroll."""
        state = controller.get_current_event_state()
        if state & Gdk.ModifierType.CONTROL_MASK:
            zoom_direction = 0
            if dy < 0:
                zoom_direction = -1  # Zoom in
            elif dy > 0:
                zoom_direction = 1   # Zoom out
            if zoom_direction != 0:
                self.apply_zoom_change(zoom_direction)
                return True
        return False

    def on_pinch_zoom_begin(self, gesture, sequence):
        """Save current font size before pinch and claim gesture."""
        self._pinch_start_size = getattr(self, '_current_zoom_size', 10.0)
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    def on_pinch_zoom_changed(self, gesture, scale):
        """Apply zoom based on pinch gesture scaling."""
        base_size = self._pinch_start_size
        new_size = max(6.0, min(base_size * scale, 36.0))
        css_provider = self._lyrics_css_provider
        css_string = f".zoomable-lyrics {{ font-size: {new_size}pt; }}"
        css_provider.load_from_data(css_string.encode())
        self._current_zoom_size = new_size
        return True

    def on_key_zoom(self, controller, keyval, keycode, state):
        """Handle zoom with Ctrl + +/- keys."""
        if not state & Gdk.ModifierType.CONTROL_MASK:
            return False

        zoom_direction = 0
        if keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            zoom_direction = -1  # Zoom in
        elif keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            zoom_direction = 1   # Zoom out
        else:
            return False

        if zoom_direction != 0:
            self.apply_zoom_change(zoom_direction)
            return True

        return False

    def apply_zoom_change(self, direction, fixed_size=None):
        """Apply zoom incrementally or fixed size."""
        current_size = getattr(self, '_current_zoom_size', 10.0)
        if fixed_size is not None:
            new_size = fixed_size
        else:
            zoom_factor = 1.0
            if direction == -1:
                new_size = min(current_size + zoom_factor, 36.0)
            elif direction == 1:
                new_size = max(current_size - zoom_factor, 6.0)
            else:
                return False

        # Final clamp
        new_size = max(6.0, min(new_size, 36.0))
        self._current_zoom_size = new_size

        # Apply CSS change
        css_provider = self._lyrics_css_provider
        css_string = f".zoomable-lyrics {{ font-size: {new_size}pt; }}"
        css_provider.load_from_data(css_string.encode())
        return True

    # -----------------------
    # FAVORITES MANAGEMENT
    # -----------------------
    def on_fav_clicked(self, button, song):
        """Toggle favorite icon and update the internal list."""
        img = button.get_child()
        if img.get_icon_name() == "non-starred-symbolic":
            img.set_from_icon_name("starred-symbolic")
            self.favorites.append(song)
        else:
            img.set_from_icon_name("non-starred-symbolic")
            if song in self.favorites:
                self.favorites.remove(song)

    # -----------------------
    # WINDOW CLOSE
    # -----------------------
    def on_close_request(self, window):
        """Save zoom and favorites on window close."""
        # Arrêter l'animation d'opacité si elle est en cours
        if self.animation_timeout_id is not None:
            GLib.source_remove(self.animation_timeout_id)
            self.animation_timeout_id = None

        try:
            os.makedirs(self.config_dir, exist_ok=True)
            config_data = {
                "zoom_size": self._current_zoom_size,
                "favorites": self.favorites,
                "cached_songs": self.cached_songs,
                "cached_searchs": self.cached_searchs
            }
            with open(self.config_file, 'w') as f:
                json.dump(config_data, f, indent=4)
        except Exception as e:
            print(f"Could not save config: {e}")
        else:
            print("Config saved")
        return False

    def _set_lyrics_with_chord_colors(self, tab_content):
        """
        Sets the text content and applies the 'chord_tag' to identified chords.
        A chord is generally a capital letter (A-G) optionally followed by
        m, sus, aug, dim, 7, 9, 11, #, b, etc.
        """
        buffer = self.lyrics_view.get_buffer()

        # 1. Reset the buffer and remove previous tags
        # This is crucial for performance and correctness
        buffer.set_text(tab_content)

        # Get iterators for the start and end of the buffer
        start_iter = buffer.get_start_iter()
        end_iter = buffer.get_end_iter()

        # Remove all instances of the chord_tag from the entire text
        buffer.remove_tag_by_name("chord_tag", start_iter, end_iter)

        # A very broad pattern, but effective for cleaning up tab content:
        chord_pattern = r'([A-G][b#]?(m|min|maj|sus|aug|dim|add|7|9|11|13)*(\/[A-G][b#]?)?)\b'

        # Find all matches using regex
        for match in re.finditer(chord_pattern, tab_content):
            text = match.group(1).strip()

            # Only process if the matched text is a plausible chord (e.g., avoid accidental matches with single letters)
            if len(text) >= 1 and not text.islower():
                start_index = match.start(1)
                end_index = match.end(1)

                # Get iterators by character index
                start_match_iter = buffer.get_iter_at_offset(start_index)
                end_match_iter = buffer.get_iter_at_offset(end_index)

                # Apply the tag
                buffer.apply_tag_by_name(
                    "chord_tag",
                    start_match_iter,
                    end_match_iter
                )

    def on_fav_song_clicked(self, button):
        """Bascule l'état favori de la chanson actuellement affichée."""
        img = self.fav_icon
        song = self.current_song

        if img.get_icon_name() == "non-starred-symbolic":
            # Ajouter aux favoris
            img.set_from_icon_name("starred-symbolic")
            if song not in self.favorites:
                self.favorites.append(song)
                print("favorite added")
        else:
            # Retirer des favoris
            img.set_from_icon_name("non-starred-symbolic")
            if song in self.favorites:
                self.favorites.remove(song)
                print("favorite removed")

    def on_leaflet_visible_child_changed(self, leaflet, pspec):
        """Cache les contrôles quand on quitte la page des accords (gestion pour AdwLeaflet)"""

        # MODIFICATION: Vérifier l'enfant visible du leaflet
        current_child = leaflet.get_visible_child()

        if current_child != self.chords_view_overlay:
            # On est sur la page du STACK (favoris ou recherche)
            self.play_pause_button.set_visible(False)
            self.speed_scale.set_visible(False)
            self.stop_scroll()  # Arrêter le défilement si on change de page
            # Arrêter l'animation d'opacité
            if self.animation_timeout_id is not None:
                GLib.source_remove(self.animation_timeout_id)
                self.animation_timeout_id = None
            # Réinitialiser l'état de la souris
            self.is_mouse_over_controls = False

            # --- Synchronisation de l'historique ---
            # Si l'historique pense qu'on est sur une chanson,
            # mais qu'on est revenu au stack (via swipe), on pop l'historique.
            current_state_type = self._get_current_state()[0]
            if current_state_type == "song":
                self.history.pop()
        else:
            # On est sur la page des ACCORDS
            self.play_pause_button.set_visible(True)
            self.speed_scale.set_visible(False)
            # S'assurer que l'opacité est correcte
            if self.scroll_timeout_id is None:
                self.start_opacity_animation(1.0)  # Pas de défilement = pleine opacité
