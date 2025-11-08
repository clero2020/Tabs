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
MAX_CACHED_SEARCHES = 1000

@Gtk.Template(resource_path='/org/clero/tabs/window.ui')
class TabsWindow(Adw.ApplicationWindow):
    """Main application window for the Tabs application."""

    __gtype_name__ = 'TabsWindow'

    # Template Children Bindings
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

    # ADW Leaflet bindings
    leaflet = Gtk.Template.Child()
    chords_view_overlay = Gtk.Template.Child()

    def __init__(self, **kwargs):
        """Initialize the main window with all components and event handlers."""
        super().__init__(**kwargs)

        # ========== STACK & LEAFLET CONFIGURATION ==========
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(400)
        # Connect to leaflet to manage control visibility
        self.leaflet.connect("notify::visible-child", self.on_leaflet_visible_child_changed)

        # ========== SEARCH CONNECTIONS ==========
        self.search_entry.connect("activate", self.on_search_activated)
        self.results_list.connect("row-activated", self.on_row_activated)
        self.favorites_list.connect("row-activated", self.on_row_activated)

        # ========== SCROLL / PLAYBACK MANAGEMENT ==========
        self.scroll_timeout_id = None
        self.scroll_speed = 1.0       # Base scroll speed
        self.scroll_interval = 50     # Update interval in ms
        self.scroll_amount = 0.5      # Base pixels to scroll per interval

        # Connect playback controls
        if self.play_pause_button:
            self.play_pause_button.connect("clicked", self.on_play_pause_clicked)
            self.play_pause_button.set_visible(False)  # Hidden by default

        if self.speed_scale:
            self.speed_scale.set_range(0.5, 5.0)
            self.speed_scale.set_value(self.scroll_speed)
            self.speed_scale.connect("value-changed", self.on_speed_scale_changed)
            self.speed_scale.set_visible(False)  # Hidden by default

        # ========== CONFIGURATION FILE ==========
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
            except (IOError, json.JSONDecodeError, ValueError) as e:
                print(f"Error loading config: {e}")
        else:
            print("No config file found")

        # ========== CACHE FILE ==========
        self.cached_songs = None
        self.cached_searches = None

        # Define cache file path
        self.cache_dir = os.environ.get("XDG_CACHE_HOME")
        self.cache_file = os.path.join(self.cache_dir, "cache.json")

        # Load cache from file
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    cache = json.load(f)
                    self.cached_songs = cache.get("cached_songs")
                    self.cached_searches = cache.get("cached_searches")
            except (IOError, json.JSONDecodeError, ValueError) as e:
                print(f"Error loading cache: {e}")
        else:
            print("No cache file found")

        if not self.cached_songs:
            self.cached_songs = []
        if not self.cached_searches:
            self.cached_searches = []

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

        # Connect favorite button on song page
        self.fav_song_button.connect("clicked", self.on_fav_song_clicked)

        # ============ HISTORY MANAGEMENT ============
        # History stack (list of states, limited to MAX_HISTORY_SIZE)
        self.history = []
        # Initialize history with the starting state
        self._push_history(["favorites"])
        self.back_button.connect("clicked", self.on_back_clicked)
        self.favorites_button.connect("clicked", self.on_favorites_clicked)

        # ========== TEXT COLORING ==========
        self.lyrics_buffer = self.lyrics_view.get_buffer()

        # Get the tag table from the buffer
        tag_table = self.lyrics_buffer.get_tag_table()
        # Create a new tag for chord coloring
        chord_tag = Gtk.TextTag.new("chord_tag")
        chord_tag.set_property("foreground", Adw.AccentColor.to_rgba(Adw.StyleManager.get_default().get_accent_color()).to_string())
        chord_tag.set_property("weight", Pango.Weight.BOLD)
        tag_table.add(chord_tag)

        # Create another tag for difficulty
        difficulty_tag = Gtk.TextTag.new("difficulty_tag")
        difficulty_tag.set_property("foreground", "red")
        tag_table.add(difficulty_tag)

        # ========== CSS FOR DIFFICULTY AND THEME ==========
        app_css_provider = Gtk.CssProvider()

        css_styles = """
        /* Target classes dynamically added to details_label */
        .difficulty-easy {
            color: @success_color; /* Use Adwaita theme success color (green) */
            font-weight: bold;
        }

        .difficulty-medium {
            color: @warning_color; /* Use Adwaita theme warning color (orange/yellow) */
            font-weight: bold;
        }

        .difficulty-hard {
            color: @destructive_color; /* Use Adwaita theme destructive color (red) */
            font-weight: bold;
        }
        """
        app_css_provider.load_from_data(css_styles.encode())

        # Apply styles to application style context
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            app_css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # ========== OPACITY ANIMATION ==========
        self.is_mouse_over_controls = False
        self.current_opacity = 1.0  # Start at full opacity
        self.target_opacity = 1.0
        self.animation_speed = 0.1  # Animation speed (higher = faster)
        self.animation_timeout_id = None

        # Mouse controllers for transparency management
        enter_controller = Gtk.EventControllerMotion.new()
        enter_controller.connect("enter", self.on_controls_enter)
        enter_controller.connect("leave", self.on_controls_leave)
        self.controls_box.add_controller(enter_controller)

        # Initial opacity
        self.controls_box.set_opacity(1.0)

    # -----------------------
    # OPACITY ANIMATION
    # -----------------------
    def animate_opacity(self):
        """Smooth opacity animation."""
        if abs(self.current_opacity - self.target_opacity) < 0.01:
            self.current_opacity = self.target_opacity
            self.controls_box.set_opacity(self.current_opacity)
            self.animation_timeout_id = None
            return False  # Stop animation

        # Linear interpolation
        self.current_opacity += (self.target_opacity - self.current_opacity) * self.animation_speed
        self.controls_box.set_opacity(self.current_opacity)
        return True  # Continue animation

    def start_opacity_animation(self, target_opacity):
        """Start animation towards target opacity."""
        self.target_opacity = target_opacity

        # Start animation if not already running
        if self.animation_timeout_id is None:
            # Ensure old animation is removed if it exists
            if self.animation_timeout_id is not None:
                 GLib.source_remove(self.animation_timeout_id)
            self.animation_timeout_id = GLib.timeout_add(16, self.animate_opacity)  # ~60 FPS

    # -----------------------
    # SCROLL HANDLERS
    # -----------------------
    def on_speed_scale_changed(self, scale):
        """Update scroll speed based on scale value."""
        self.scroll_speed = scale.get_value()

    def start_scroll(self):
        """Start automatic scrolling."""
        if self.scroll_timeout_id is None and self.chords_scrolled_window:
            # Update interval in ms
            self.scroll_timeout_id = GLib.timeout_add(
                self.scroll_interval,
                self._auto_scroll_step
            )
            # Update icon and visibility
            self.play_pause_button.set_icon_name("media-playback-pause-symbolic")
            self.speed_scale.set_visible(True)

            # Animate to transparency only if mouse is not over controls
            if not self.is_mouse_over_controls:
                self.start_opacity_animation(0.3)

    def stop_scroll(self):
        """Stop automatic scrolling."""
        if self.scroll_timeout_id is not None:
            GLib.source_remove(self.scroll_timeout_id)
            self.scroll_timeout_id = None
            # Update icon and visibility
            self.play_pause_button.set_icon_name("media-playback-start-symbolic")
            self.speed_scale.set_visible(False)

            # Animate to full opacity when scrolling stops
            self.start_opacity_animation(1.0)

    def _auto_scroll_step(self):
        """Perform a small scroll step."""
        if not self.chords_scrolled_window:
            return GLib.SOURCE_REMOVE

        adj = self.chords_scrolled_window.get_vadjustment()

        # Calculate new scroll amount based on adjusted speed
        new_value = adj.get_value() + (self.scroll_amount * self.scroll_speed)

        # Upper is total content height, Page Size is visible window height
        max_value = adj.get_upper() - adj.get_page_size()

        if new_value >= max_value:
            # Reached end: stop scrolling
            adj.set_value(max_value)  # Ensure we're at the bottom
            self.stop_scroll()
            return GLib.SOURCE_REMOVE  # Stop timer
        else:
            adj.set_value(new_value)
            return GLib.SOURCE_CONTINUE  # Continue timer

    def on_play_pause_clicked(self, button):
        """Toggle between play and pause."""
        # Check if we're on the chords view
        if self.leaflet.get_visible_child() != self.chords_view_overlay:
            return

        if self.scroll_timeout_id is None:
            self.start_scroll()
        else:
            self.stop_scroll()

    def on_controls_enter(self, controller, x, y):
        """When mouse enters controls area."""
        self.is_mouse_over_controls = True
        # Always go to full opacity on hover
        self.start_opacity_animation(1.0)

    def on_controls_leave(self, controller):
        """When mouse leaves controls area."""
        self.is_mouse_over_controls = False
        # If scrolling is active, return to transparency
        if self.scroll_timeout_id is not None:
            self.start_opacity_animation(0.3)

    # -----------------------
    # HISTORY HELPERS
    # -----------------------
    def _push_history(self, new_state):
        """Add a new state to the history stack and limit its size."""
        # Prevent stacking the same state repeatedly
        if self.history and self.history[-1] == new_state:
            return

        self.history.append(new_state)
        # Limit the history size
        if len(self.history) > MAX_HISTORY_SIZE:
            # Remove the oldest state
            del self.history[0]

    def _get_current_state(self):
        """Return the current state (last element in the stack)."""
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

        # TITLE and ARTIST
        title_markup = f'<span size="large" weight="bold">{song["song"]}</span>'
        title_label = Gtk.Label(label="", xalign=0)
        title_label.set_markup(title_markup)

        # Enable word wrapping (GTK4)
        title_label.set_wrap(True)
        title_label.set_wrap_mode(Pango.WrapMode.WORD)
        title_label.set_max_width_chars(100)
        title_label.set_justify(Gtk.Justification.LEFT)
        title_label.set_hexpand(True)

        main_grid.attach(title_label, 0, 0, 2, 1)  # Takes 2 columns

        artist_label = Gtk.Label(label=song.get('artist', 'N/A'), xalign=0)
        artist_label.add_css_class("body")
        main_grid.attach(artist_label, 0, 1, 1, 1)

        # TYPE and RATING aligned to the right
        type_label = Gtk.Label(label=f'Type: {song.get("type", "N/A")}', xalign=0)
        type_label.add_css_class("caption")
        main_grid.attach(type_label, 0, 2, 1, 1)

        rating_label = Gtk.Label(label=f'Rating: {song.get("rating_full", "0")}', xalign=1)
        rating_label.add_css_class("caption")
        main_grid.attach(rating_label, 1, 2, 1, 1)

        # Horizontal box: grid + spacer
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hbox.append(main_grid)

        # Spacer to push content to fill space
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        hbox.append(spacer)

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
        """Handle search entry activation (Enter key)."""
        text = entry.get_text()
        if text:
            songs = None
            for cached_search in self.cached_searches:
                if cached_search[0] == text:
                    songs = cached_search[1]
                    break
            if not songs:
                songs = fetch_freetar_results(text)
                self.cached_searches.append([text, songs])
                print("Added to cache")

            if len(self.cached_searches) >= MAX_CACHED_SEARCHES:
                self.cached_searches.pop(0)
                print("Removed oldest cached search")

            # Clear previous results
            children_to_remove = list(self.results_list)
            for row in children_to_remove:
                 self.results_list.remove(row)

            for song in songs:
                self._add_song_to_list(song, self.results_list)

            # Ensure we're on the correct leaflet child
            if self.leaflet.get_visible_child() == self.chords_view_overlay:
                 # Go back to stack before changing stack page
                 self.leaflet.navigate(Adw.NavigationDirection.BACK)

            self.stack.set_visible_child_name("results")
            # Update history
            self._push_history(["search", songs])
            self.songs_searched = songs

    def on_row_activated(self, listbox, row):
        """Handle song row activation (click)."""
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

        # Navigate to chords view
        self.leaflet.set_visible_child(self.chords_view_overlay)

        if len(self.cached_songs) >= MAX_CACHED_SONGS:
            self.cached_songs.pop(0)
            print("Removed oldest cached song")

        # SHOW SCROLLING CONTROLS
        self.play_pause_button.set_visible(True)
        self.speed_scale.set_visible(False)

        # Reset play/pause button state
        self.stop_scroll()  # Ensure scrolling is stopped
        self.play_pause_button.set_icon_name("media-playback-start-symbolic")

        # Initial state - full opacity since no scrolling
        self.current_opacity = 1.0
        self.target_opacity = 1.0
        self.controls_box.set_opacity(1.0)
        self.is_mouse_over_controls = False
        self.title_label.set_text(f"Title: {song_data['title']}")
        self.artist_label.set_text(f"Artist: {song_data['artist']}")
        difficulty = song_data['difficulty'].lower()

        # --- NEW DIFFICULTY COLOR LOGIC ---
        # 1. Update text
        self.details_label.set_text(
            f"Tuning: {song_data['tuning']} — Capo: {song_data['capo']} — Difficulty: {song_data['difficulty']} — Type: {song_data['type']}"
        )

        # 2. Remove all previous difficulty classes
        self.details_label.remove_css_class("difficulty-easy")
        self.details_label.remove_css_class("difficulty-medium")
        self.details_label.remove_css_class("difficulty-hard")

        # 3. Apply new CSS class
        if 'easy' in difficulty or 'novice' in difficulty or 'beginner' in difficulty:
            self.details_label.add_css_class("difficulty-easy")
        elif 'medium' in difficulty or 'intermediate' in difficulty:
            self.details_label.add_css_class("difficulty-medium")
        elif 'hard' in difficulty or 'expert' in difficulty:
            self.details_label.add_css_class("difficulty-hard")

        # --- SYNCHRONIZE FAVORITE BUTTON ---
        for song in self.songs_searched:
            if url in song["song_url"]:
                self.current_song = song
                break
        is_favorite = self.current_song in self.favorites
        icon_name = "starred-symbolic" if is_favorite else "non-starred-symbolic"
        self.fav_icon.set_from_icon_name(icon_name)

        self.source_link.set_uri(song_data['original_url'])
        self.source_link.set_label("View on Ultimate Guitar")

        # Apply text and chord coloring
        self._set_lyrics_with_chord_colors(song_data['tab_content'])

        # Update history
        self._push_history(["song", song_data])

    def on_favorites_clicked(self, button):
        """Handle favorites button click."""
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
        """Handle back button click, navigating through history."""
        # History must contain at least one state and one previous state
        if len(self.history) <= 1:
            return

        # 1. Remove the current state from the history stack
        current_state = self.history.pop()

        # 2. Get the new current state (the destination)
        destination_state = self._get_current_state()
        state_type = destination_state[0]

        # 3. Render the destination state
        if state_type == "favorites":
            # Navigate leaflet back if needed
            self.leaflet.navigate(Adw.NavigationDirection.BACK)
            self.stack.set_visible_child_name("favorites")
            # Reload favorites list
            for child in list(self.favorites_list):
                self.favorites_list.remove(child)
            for song in self.favorites:
                self._add_song_to_list(song, self.favorites_list)

        elif state_type == "search":
            # Navigate leaflet back if needed
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
            # Navigate leaflet to chords view
            song_data = destination_state[1]
            self.leaflet.set_visible_child(self.chords_view_overlay)
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
        # Stop opacity animation if running
        if self.animation_timeout_id is not None:
            GLib.source_remove(self.animation_timeout_id)
            self.animation_timeout_id = None

        # Save config
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            config_data = {
                "zoom_size": self._current_zoom_size,
                "favorites": self.favorites
            }
            with open(self.config_file, 'w') as f:
                json.dump(config_data, f, indent=4)
        except Exception as e:
            print(f"Could not save config: {e}")
        else:
            print("Config saved")

        # Save cache
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            cache_data = {
                "cached_songs": self.cached_songs,
                "cached_searches": self.cached_searches
            }
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=4)
        except Exception as e:
            print(f"Could not save cache: {e}")
        else:
            print("Cache saved")
        return False

    def _set_lyrics_with_chord_colors(self, tab_content):
        """
        Set text content and apply 'chord_tag' to identified chords.

        Args:
            tab_content (str): The tab content with chords and lyrics
        """
        buffer = self.lyrics_view.get_buffer()

        # Reset the buffer and remove previous tags
        buffer.set_text(tab_content)

        # Get iterators for the start and end of the buffer
        start_iter = buffer.get_start_iter()
        end_iter = buffer.get_end_iter()

        # Remove all instances of the chord_tag from the entire text
        buffer.remove_tag_by_name("chord_tag", start_iter, end_iter)

        # Pattern for identifying chords in tab content
        chord_pattern = r'([A-G][b#]?(m|min|maj|sus|aug|dim|add|7|9|11|13)*(\/[A-G][b#]?)?)\b'

        # Find all matches using regex
        for match in re.finditer(chord_pattern, tab_content):
            text = match.group(1).strip()

            # Only process if the matched text is a plausible chord
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
        """Toggle favorite status of the currently displayed song."""
        img = self.fav_icon
        song = self.current_song

        if img.get_icon_name() == "non-starred-symbolic":
            # Add to favorites
            img.set_from_icon_name("starred-symbolic")
            if song not in self.favorites:
                self.favorites.append(song)
                print("Favorite added")
        else:
            # Remove from favorites
            img.set_from_icon_name("non-starred-symbolic")
            if song in self.favorites:
                self.favorites.remove(song)
                print("Favorite removed")

    def on_leaflet_visible_child_changed(self, leaflet, pspec):
        """Hide controls when leaving chords page (AdwLeaflet management)."""
        current_child = leaflet.get_visible_child()

        if current_child != self.chords_view_overlay:
            # On STACK page (favorites or search)
            self.play_pause_button.set_visible(False)
            self.speed_scale.set_visible(False)
            self.stop_scroll()  # Stop scrolling if changing page
            # Stop opacity animation
            if self.animation_timeout_id is not None:
                GLib.source_remove(self.animation_timeout_id)
                self.animation_timeout_id = None
            # Reset mouse state
            self.is_mouse_over_controls = False

            # --- History synchronization ---
            # If history thinks we're on a song but we returned to stack (via swipe), pop history
            current_state_type = self._get_current_state()[0]
            if current_state_type == "song":
                self.history.pop()
        else:
            # On CHORDS page
            self.play_pause_button.set_visible(True)
            self.speed_scale.set_visible(False)
            # Ensure opacity is correct
            if self.scroll_timeout_id is None:
                self.start_opacity_animation(1.0)  # No scrolling = full opacity
