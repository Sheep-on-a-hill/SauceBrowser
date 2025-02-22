"""
Sauce Selector Application

Refactored to improve readability, reduce duplication, 
and structure the code with a fully asynchronous CoverLoader.
"""

# --------------------
# Imports
# --------------------

# Standard library
import os
import random
import subprocess
import logging
import asyncio
import threading
import aiohttp
from urllib.parse import urljoin
from io import BytesIO

# Third-party
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageTk

import tkinter as tk
from tkinter import ttk, Toplevel, messagebox, simpledialog
from tkinter.ttk import Progressbar
from ttkthemes import ThemedTk

# Local modules
import data_manager_json as dm
from TagFinder import tag_fetch

# --------------------
# Constants & Globals
# --------------------

# Load app settings from JSON
app_settings = dm.load_settings()

INFO_DIR = app_settings["paths"]["info_directory"]
COVERS_DIR = app_settings["paths"]["covers_directory"]

log_file_path = app_settings["paths"]["log_file"]
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

logging.basicConfig(
    filename=log_file_path,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Max tries for network requests
NETWORK_CFG = app_settings["network"]
RETRY_ATTEMPTS = NETWORK_CFG["retry_attempts"]
TIMEOUT = NETWORK_CFG["timeout"]
PROXY_URL = NETWORK_CFG["proxy"]
PROXIES = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None

CONCURRENT_FETCHES = 5  # Limit how many cover-URL fetches happen at once


# --------------------
# Helper Classes & Functions
# --------------------

class CoverLoader:
    """
    An asynchronous cover loader that:
      - Retrieves cover URLs for nhentai codes.
      - Caches results to avoid refetching.
      - Uses a semaphore to limit concurrency.
    """

    def __init__(self):
        self.cover_cache = {}            # code -> cover_url (string or None)
        self.session = None              # aiohttp.ClientSession (created lazily)
        self.sem = asyncio.Semaphore(CONCURRENT_FETCHES)
        self._session_lock = asyncio.Lock()

    async def open_session(self):
        """Create the aiohttp session if not already open."""
        async with self._session_lock:  # Ensure only one task can open the session at a time
            if not self.session:
                timeout = aiohttp.ClientTimeout(total=TIMEOUT)
                self.session = aiohttp.ClientSession(timeout=timeout)
                logging.info("aiohttp session opened.")
            else:
                logging.debug("Session already open.")

    async def close_session(self):
        """Close the aiohttp session if open."""
        if self.session:
            await self.session.close()
            self.session = None
            logging.info("aiohttp session closed.")
        else:
            logging.warning("No session to close.")

    async def fetch_cover_url(self, code: int) -> str:
        """
        Low-level async method that does the actual HTTP get to nhentai.net/g/<code>
        and parses out the cover URL. Retries up to RETRY_ATTEMPTS.
        """
        url = f"https://nhentai.net/g/{code}/"

        for attempt in range(RETRY_ATTEMPTS):
            try:
                async with self.session.get(url, proxy=PROXY_URL) as resp:
                    if resp.status != 200:
                        logging.warning(f"[fetch_cover_url] Failed to fetch {url} (status: {resp.status}).")
                        return None

                    html = await resp.text()
                    soup = BeautifulSoup(html, "html.parser")

                    img_tags = soup.find_all("img")
                    if len(img_tags) < 2:
                        logging.warning(f"[fetch_cover_url] No suitable images found for code {code}.")
                        return None

                    # Typically, the second <img> is the cover
                    img_tag = img_tags[1]
                    img_url = (
                        img_tag.get("data-src")
                        or img_tag.get("data-lazy-src")
                        or img_tag.get("data-original")
                        or img_tag.get("src")
                    )

                    # Ensure it's an absolute URL
                    if img_url and not img_url.startswith("http"):
                        img_url = urljoin(url, img_url)

                    # logging.info(f"[fetch_cover_url] Found cover image for code {code}: {img_url}")
                    return img_url

            except Exception as e:
                logging.error(f"[fetch_cover_url] Attempt {attempt+1}: Failed to fetch {url}: {e}")

        logging.error(f"[fetch_cover_url] All attempts failed for code {code}.")
        return None

    async def load_cover_image_if_needed(self, code: int) -> str:
        """
        Public method to get the cover URL for a given code.
          - Checks our in-memory cache first.
          - If missing, fetches with fetch_cover_url (sem-protected).
        Returns the cover URL or None if it fails.
        """
        if code in self.cover_cache:
            return self.cover_cache[code]

        # Make sure we have a session
        await self.open_session()

        # Limit concurrency via semaphore
        async with self.sem:
            cover_url = await self.fetch_cover_url(code)

        # Cache it (even if None) so we don't keep retrying
        self.cover_cache[code] = cover_url
        return cover_url


def open_in_browser(code, page=None):
    """
    Open the specified code in a private Firefox window.
    If page is specified, open that page in the gallery.
    """
    base_url = f'https://nhentai.net/g/{code}'
    url = f'{base_url}/{page}/' if page else f'{base_url}/'
    subprocess.run([r"C:\Program Files\Mozilla Firefox\firefox.exe", "--private-window", url])


def load_cover_image_sync(cover_url, size=(100, 150), load_images=True):
    """
    Synchronous helper to download cover bytes (if `load_images`), 
    then return a PIL ImageTk.PhotoImage. If `cover_url` is None or fetch fails, returns None.
    """
    if not load_images or not cover_url:
        return None
    

    try:
        resp = requests.get(cover_url, timeout=TIMEOUT, proxies=PROXIES)
        if resp.status_code != 200:
            logging.warning(f"Failed to download image from {cover_url}")
            return None

        image_data = BytesIO(resp.content)
        image = Image.open(image_data).resize(size)
        return ImageTk.PhotoImage(image)
    except Exception as e:
        logging.error(f"Error loading image from '{cover_url}': {e}")
        return None


def get_name(code):
    """
    Fetch the "pretty" name/title of the given code from nhentai.
    Implements simple retry and optional proxy usage.
    """
    url = f'https://nhentai.net/g/{code}/'
    for attempt in range(RETRY_ATTEMPTS):
        try:
            resp = requests.get(url, timeout=TIMEOUT, proxies=PROXIES)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "html.parser")
                name_tag = soup.find('span', class_='pretty')
                return name_tag.text if name_tag else "Unknown Name"
            else:
                logging.warning(f"Failed to fetch {url} with status {resp.status_code}")
        except Exception as e:
            logging.error(f"Request attempt {attempt+1} failed: {e}")
    return "Unknown Name"


def code_read():
    """Return a dict {code: {...}} from JSON (the main data)."""
    return dm.load_codes_json()


def get_tags(banned_tags):
    """
    Example command to run a separate Python script for tag usage 
    (Not used in the final code, but kept for reference).
    """
    subprocess.run(["python", "TagTest.py", banned_tags])


# --------------------
# Main Application
# --------------------

class MultiPageApp:
    """
    Main application. Houses the Tk root, overall settings, pages, etc.
    """

    def __init__(self):
        self.settings = dm.load_settings()

        # Update directories based on settings
        global INFO_DIR
        INFO_DIR = self.settings["paths"]["info_directory"]
        os.makedirs(INFO_DIR, exist_ok=True)

        # 1) Create a background asyncio event loop
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

        # 2) Initialize ThemedTk
        self.root = ThemedTk(theme=self.settings["theme"]["name"])
        default_size = self.settings["app"].get("window_size", "400x510")
        self.root.geometry(default_size)
        self.root.title("Sauce Selector")

        # Configure global style
        self.style = ttk.Style(self.root)
        font_family = self.settings["theme"]["font_family"]
        font_size = self.settings["theme"]["font_size"]
        self.style.configure(".", font=(font_family, font_size))

        # Show a loading label initially
        self.loading_label = ttk.Label(self.root, text="Loading data, please wait...")
        self.loading_label.pack(pady=50)

        # Full list of codes loaded from JSON
        self.full_list = dm.load_codes_json()
        # Only codes marked visible
        self.master_list = {
            key: value for key, value in self.full_list.items() if value.get('visible') == 1
        }

        self.current_theme = self.settings['theme']['name']

        # 3) Create the CoverLoader (async) for retrieving cover URLs
        self.cover_loader = CoverLoader()

        # Open the aiohttp session asynchronously
        future = asyncio.run_coroutine_threadsafe(self.cover_loader.open_session(), self.loop)
        future.result()

        # 4) Run data loading in a background thread
        threading.Thread(target=self.load_data_async, args=(self.master_list,)).start()

    def list_update(self, codes_dict):
        """Update in-memory lists and save to JSON."""
        self.master_list = {
            key: value for key, value in codes_dict.items() if value.get('visible') == 1
        }
        dm.save_codes_json(codes_dict)

    def load_data_async(self, codes_dict):
        """Load data in a separate thread, then init UI on main thread."""
        try:
            # Instead of asyncio.run(...), use a separate function that we can call directly
            # or schedule with run_coroutine_threadsafe
            future = asyncio.run_coroutine_threadsafe(self.load_data(codes_dict), self.loop)
            future.result()  # Wait for completion
            self.root.after(0, self.initialize_ui)  # Schedule UI init in the main Tk thread
        except Exception as e:
            logging.error(f"Error loading data: {e}", exc_info=True)

    async def load_data(self, codes_dict):
        """
        Example spot for background tasks like auto-updates.
        """
        self.tags = dm.read_tags()
        # Optionally, await a small delay
        await asyncio.sleep(1)

    def initialize_ui(self):
        self.loading_label.destroy()

        # Menu for theme settings
        self.style_menu = tk.Menu(self.root)
        self.root.config(menu=self.style_menu)
        self.theme_menu = tk.Menu(self.style_menu, tearoff=0)
        self.style_menu.add_cascade(label="File", menu=self.theme_menu)
        self.theme_menu.add_command(label='Options', command=self.open_theme_selector)

        # Create the notebook
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)
        self.pages = []

        # Add pages (could rename them to something more descriptive)
        self.add_page(HomePage, "Home Page")
        self.add_page(lambda p, n, c: PageOne(p, n, c), "Sauce selection")
        self.add_page(PageTwo, "Favorites")
        self.add_page(PageThree, "Sauce list updater")
        self.add_page(PageFour, "Statistics")

        # Adjust window size whenever tab changes
        self.notebook.bind("<<NotebookTabChanged>>", self.adjust_window_size)
        self.adjust_window_size()

    def add_page(self, page_class, title):
        """Instantiate and add a page to the notebook."""
        if callable(page_class):
            page_instance = page_class(self.notebook, self.notebook, self)
        else:
            page_instance = page_class(self.notebook, self.notebook, self)
        self.notebook.add(page_instance, text=title)
        self.pages.append(page_instance)

    def get_page(self, index):
        """Return a reference to a page by its index in the notebook."""
        return self.pages[index]

    def update_all_pages(self):
        """Convenience method to call `update_page()` on every page (if it exists)."""
        for page in self.pages:
            if hasattr(page, 'update_page'):
                page.update_page()

    def adjust_window_size(self, event=None):
        """Auto-size the window to fit the current page's requested size."""
        if not hasattr(self, 'notebook'):
            return
        current_page = self.notebook.nametowidget(self.notebook.select())
        current_page.update_idletasks()
        width = current_page.winfo_reqwidth()
        height = current_page.winfo_reqheight()

        # Impose minimum widths/heights if desired
        if width < 500:
            width = 500

        self.root.geometry(f"{width+20}x{height+30}")

    def mainloop(self):
        self.root.mainloop()

        # On exit, close the aiohttp session (if open) using the background loop
        try:
            future = asyncio.run_coroutine_threadsafe(self.cover_loader.close_session(), self.loop)
            future.result()
        except:
            pass

        # Stop the background loop
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join()

    def open_theme_selector(self):
        """Open the theme selector popup."""
        ThemeSelectorPopup(self)


class ThemeSelectorPopup(tk.Toplevel):
    def __init__(self, controller):
        super().__init__(controller.root)
        self.controller = controller
        self.title("Options")
        self.geometry("300x300")

        self.style = ttk.Style(self.controller.root)
        bg_color = self.style.lookup("TFrame", "background") or "SystemButtonFace"
        self.configure(bg=bg_color)

        label = ttk.Label(self, text="Select a Theme", font=(self.controller.settings["theme"]["font_family"], 16))
        label.pack(pady=20)

        # List of available themes
        self.themes = self.controller.root.get_themes()
        self.themes.sort()

        # Current theme as default
        self.selected_theme = ttk.Combobox(self, values=self.themes, state="readonly")
        self.selected_theme.set(self.controller.current_theme)
        self.selected_theme.pack(pady=10)

        apply_button = ttk.Button(self, text="Apply Theme", command=self.apply_theme)
        apply_button.pack(pady=10)

        reset_button = ttk.Button(self, text="Reset Codes", command=self.reset_code_visible)
        reset_button.pack()

    def apply_theme(self):
        new_theme = self.selected_theme.get()
        self.controller.root.set_theme(new_theme)
        self.controller.current_theme = new_theme

        # Persist to settings
        self.controller.settings["theme"]["name"] = new_theme
        dm.write_settings(self.controller.settings)

        # Update the popup's background to the new theme color
        bg_color = self.style.lookup("TFrame", "background") or "SystemButtonFace"
        self.configure(bg=bg_color)

    def reset_code_visible(self):
        # Confirmation dialog
        confirm = messagebox.askyesno(
            "Confirm Reset",
            "Are you sure you want to reset all codes? This action cannot be undone."
        )
        if confirm:
            all_keys = list(self.controller.full_list.keys())
            for key in all_keys:
                self.controller.full_list[key]['visible'] = 1
            dm.save_codes_json(self.controller.full_list)
            messagebox.showinfo("Reset Complete", "All codes have been reset successfully.")


# --------------------
# Pages
# --------------------

class HomePage(ttk.Frame):
    """
    The Home Page, showing a welcome label and a togglable "section" frame
    for entering a code, marking progress, discarding, etc.
    """
    def __init__(self, parent, notebook, controller):
        super().__init__(parent)
        self.notebook = notebook
        self.controller = controller
        self.section_shown = False
        self.in_progress = []
        self.in_progress_dict = {}

        ttk.Label(self, text="Welcome to the sauce selector", font=(self.controller.settings["theme"]["font_family"], 16)).pack(pady=20)

        # In-progress comics region
        self.in_progress_frame = ttk.Frame(self, borderwidth=2, relief="ridge")
        # Toggable data entry region
        self.section_frame = ttk.Frame(self, borderwidth=2, relief="ridge")
        # Toggle button region
        self.toggle_button_frame = ttk.Frame(self)

        # Code entry
        self.section_label = ttk.Label(self.section_frame, text="Which code?")
        self.code_progress_entry = ttk.Entry(self.section_frame, width=8)
        self.section_label.grid(row=0, column=0, padx=10, pady=10)
        self.code_progress_entry.grid(row=0, column=1, padx=10, pady=10)

        # Checkbox for incomplete progress
        self.comp_var = tk.BooleanVar(value=False)
        self.comp_checkbox = ttk.Checkbutton(
            self.section_frame,
            text="Incomplete?",
            variable=self.comp_var,
            command=self.toggle_completion_frame
        )
        self.comp_checkbox.grid(row=1, column=0, pady=10)

        self.comp_frame = self.create_completion_frame(self.section_frame)
        self.like_frame = self.create_like_frame(self.section_frame)
        self.comp_frame.grid_forget()
        self.like_frame.grid(row=1, column=1, pady=10)

        # Toggle button to show/hide the section
        self.toggle_button = ttk.Button(
            self.toggle_button_frame, 
            text="Show Section", 
            command=self.toggle_section
        )
        self.toggle_button.pack(pady=10)

        self.update_page()

    def load_in_progress_data(self):
        """Load 'in_progress' dict from settings."""
        return self.controller.settings['in_progress']

    def display_in_progress_comics(self):
        """Display each in-progress code as a clickable button (with or without cover image)."""
        in_progress_label = ttk.Label(self.in_progress_frame, text='In progress comics')
        in_progress_label.grid(row=0, column=0, columnspan=6, pady=5)

        # Clear everything but the main label
        for widget in self.in_progress_frame.winfo_children():
            if widget != in_progress_label:
                widget.destroy()

        # Config columns for spacing
        for col in range(6):
            self.in_progress_frame.columnconfigure(col, weight=0, minsize=100)

        # Decide button size
        if self.controller.settings['images']:
            btn_height = 150
            btn_width = 100
        else:
            btn_height = 8
            btn_width = 10

        # Prepare list to store PhotoImage objects (so they don't get GC'd)
        self.images = []

        # For each code in in_progress, load the cover URL using the background loop
        for idx, code_str in enumerate(self.in_progress):
            code_int = int(code_str)
            
            cover_url = self.controller.full_list.get(code_int, {}).get('cover')
            if cover_url is None or cover_url == "":
                cover_url = self.get_cover_url_sync(code_int)
                self.controller.full_list[code_int]['cover'] = cover_url
                
            image_path = os.path.join(COVERS_DIR, f"{code_int}.jpg")
            if os.path.exists(image_path):
                img = Image.open(image_path).resize((100, 150))
                photo_img = ImageTk.PhotoImage(img)
                
            else:
                photo_img = load_cover_image_sync(
                    cover_url,
                    size=(100, 150),
                    load_images=self.controller.settings['images']
                )
            self.images.append(photo_img)

            row = (idx // 6) + 1
            col = idx % 6
            button = tk.Button(
                self.in_progress_frame,
                text=str(code_str),
                image=self.images[idx],
                compound="center",
                font=(self.controller.settings["theme"]["font_family"], self.controller.settings["theme"]["font_size"]),
                width=btn_width,
                height=btn_height,
                command=lambda c=(code_str, self.in_progress_dict[code_str]): self.open_in_progress_code(c)
            )
            button.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")

    def get_cover_url_sync(self, code_int):
        """
        Schedule load_cover_image_if_needed(code_int) on the background loop
        and block until it returns. This avoids calling asyncio.run(...).
        """
        future = asyncio.run_coroutine_threadsafe(
            self.controller.cover_loader.load_cover_image_if_needed(code_int),
            self.controller.loop
        )
        return future.result()

    def create_completion_frame(self, parent):
        """Sub-frame for specifying page number when marking incomplete progress."""
        frame = ttk.Frame(parent, borderwidth=2, relief="ridge")
        comp_label = ttk.Label(frame, text="What page?")
        self.page_number_entry = ttk.Entry(frame, width=5)
        comp_submit = ttk.Button(frame, text='Submit', command=self.save_progress)

        comp_label.grid(row=0, column=0, pady=10, padx=10)
        self.page_number_entry.grid(row=0, column=1, pady=10, padx=10)
        comp_submit.grid(row=0, column=2, pady=10, padx=10)
        return frame

    def create_like_frame(self, parent):
        """Sub-frame for marking a code as Favorite or Discard."""
        frame = ttk.Frame(parent, borderwidth=2, relief="ridge")
        like_button = ttk.Button(frame, text='Favorite', command=self.favorite)
        discard_button = ttk.Button(frame, text='Discard', command=self.discard)
        like_button.grid(row=0, column=1, pady=10, padx=10)
        discard_button.grid(row=0, column=2, pady=10, padx=10)
        return frame

    def toggle_completion_frame(self):
        """Show or hide the 'page number' frame depending on whether 'Incomplete?' is checked."""
        if self.comp_var.get():
            self.comp_frame.grid(row=1, column=1, pady=10)
            self.like_frame.grid_forget()
        else:
            self.comp_frame.grid_forget()
            self.like_frame.grid(row=1, column=1, pady=10)
        self.controller.adjust_window_size()

    def toggle_section(self):
        """Toggle display of the entire 'section_frame'."""
        if self.section_shown:
            self.section_frame.pack_forget()
            self.toggle_button.config(text="Show Section")
        else:
            self.section_frame.pack(pady=20, padx=20, fill="x")
            self.toggle_button.config(text="Hide Section")
        self.section_shown = not self.section_shown
        self.controller.adjust_window_size()

    def show_section(self):
        """Force the 'section_frame' to be shown."""
        if not self.section_shown:
            self.section_frame.pack(pady=20, padx=20, fill="x")
            self.toggle_button.config(text="Hide Section")
            self.section_shown = True
        self.controller.adjust_window_size()

    def favorite(self):
        """Mark the code as a favorite and remove it from visible/in-progress."""
        code_str = self.code_progress_entry.get().strip()
        if not code_str:
            return
        try:
            code = int(code_str)
        except ValueError:
            logging.warning(f"Invalid code: {code_str}")
            return

        # Actually fetch name from the site
        name = get_name(code)

        # Add to favorites
        if code in self.controller.full_list:
            tags = self.controller.full_list[code].get('tags', [])
        else:
            tags = []
        dm.add_favorites_json({code: {'tags': tags, 'name': name}})

        # Mark invisible in the main list
        if code in self.controller.master_list:
            self.controller.full_list[code]['visible'] = 0
            self.controller.list_update(self.controller.full_list)

            # Remove from in_progress as well
            if str(code) in self.controller.settings['in_progress']:
                del self.controller.settings['in_progress'][str(code)]
                dm.write_settings(self.controller.settings)

        # If the code was in the local list, remove it
        if code_str in self.in_progress:
            del self.controller.settings['in_progress'][str(code)]
            dm.write_settings(self.controller.settings)

        self._reset_entries()
        self.toggle_section()
        self.controller.update_all_pages()

    def discard(self):
        """Discard the code, removing its cover and marking it invisible."""
        code_str = self.code_progress_entry.get().strip()
        if not code_str:
            return
        try:
            code = int(code_str)
        except ValueError:
            logging.warning(f"Invalid code: {code_str}")
            return

        if code in self.controller.master_list:
            self.controller.full_list[code]['visible'] = 0
            self.controller.list_update(self.controller.full_list)

            cover_path = os.path.join(COVERS_DIR, f"{code}.jpg")
            if os.path.exists(cover_path):
                os.remove(cover_path)

        if code_str in self.in_progress:
            del self.controller.settings['in_progress'][str(code)]
            dm.write_settings(self.controller.settings)

        self._reset_entries()
        self.toggle_section()
        self.controller.update_all_pages()

    def save_progress(self):
        """
        Mark code as in-progress with a page number, 
        and set 'visible' to 0 so it won't appear on the random pages again.
        """
        code_str = self.code_progress_entry.get().strip()
        page_str = self.page_number_entry.get().strip()
        if not code_str:
            return

        try:
            code = int(code_str)
        except ValueError:
            logging.warning(f"Invalid code: {code_str}")
            return

        if code in self.controller.master_list:
            self.controller.full_list[code]['visible'] = 0
            self.controller.list_update(self.controller.full_list)

        self.controller.settings['in_progress'][str(code)] = page_str
        dm.write_settings(self.controller.settings)

        self._reset_entries()
        self.toggle_section()
        self.controller.update_all_pages()

    def open_in_progress_code(self, code_tuple):
        """
        If there's a specific page stored, open that page in a private Firefox window,
        then auto-fill the code in the 'section_frame' so user can update or finalize.
        """
        code, page = code_tuple
        open_in_browser(code, page)
        self.show_section()
        self.code_progress_entry.delete(0, tk.END)
        self.code_progress_entry.insert(0, code)

    def update_page(self):
        """Refresh in-progress data and update the UI."""
        self.in_progress_dict = self.load_in_progress_data()
        self.in_progress = list(self.in_progress_dict.keys())

        self.toggle_button_frame.pack_forget()
        for widget in self.in_progress_frame.winfo_children():
            widget.destroy()

        if self.in_progress:
            self.in_progress_frame.pack(pady=20)
            self.display_in_progress_comics()
        else:
            self.in_progress_frame.pack_forget()

        self.toggle_button_frame.pack()
        self.controller.adjust_window_size()

    def _reset_entries(self):
        self.code_progress_entry.delete(0, tk.END)
        self.page_number_entry.delete(0, tk.END)


class PageOne(ttk.Frame):
    """
    Page that displays random codes as clickable images.
    Users can filter by tags, toggle image loading, etc.
    """
    def __init__(self, parent, notebook, controller):
        super().__init__(parent)
        self.notebook = notebook
        self.controller = controller

        self.button_width = 150
        self.button_height = 225
        self.search_filter = []

        # Filter frame
        self.search_frame = ttk.Frame(self)
        self.search_frame.pack(pady=5)

        self.filter_entry = ttk.Entry(self.search_frame, width=20)
        self.filter_entry.bind("<Return>", lambda event: self.apply_filter())
        self.filter_entry.pack(side=tk.LEFT, padx=5)
        self.filter_entry.insert(0, "")

        # Checkbox for images
        self.image_checkbox_frame = ttk.Frame(self)
        self.image_checkbox_frame.pack()

        self.image_var = tk.BooleanVar(value=self.controller.settings['images'])
        self.image_checkbox = ttk.Checkbutton(
            self.image_checkbox_frame,
            text="Load images",
            variable=self.image_var,
            command=self.toggle_image_load
        )
        self.image_checkbox.pack()

        self.filter_button = ttk.Button(self.search_frame, text="Filter", command=self.apply_filter)
        self.filter_button.pack(side=tk.LEFT, padx=5)

        self.clear_button = ttk.Button(self.search_frame, text="Clear", command=self.clear_filter)
        self.clear_button.pack(side=tk.LEFT, padx=5)

        # Frame for the code buttons
        self.code_buttons_frame = ttk.Frame(self)
        self.code_buttons_frame.pack(pady=10)

        self.refresh_button = ttk.Button(self, text='Refresh', command=self.refresh_codes)
        self.refresh_button.pack(pady=10)

        self.loading_label = ttk.Label(self, text="")
        self.loading_label.pack(pady=5)
        
        # Right-click menu
        self.current_button = None
        self.popup_menu = tk.Menu(self, tearoff=0)
        self.popup_menu.add_command(label="Remove", command=self.hide_code)

        self.update_page()
        
    def show_popup(self, event):
        self.current_button = event.widget
        self.popup_menu.tk_popup(event.x_root, event.y_root)
        
    def hide_code(self):
        if self.current_button is None:
            return
        code = getattr(self.current_button, 'code_val', None)
        if code is None:
            return
        self.controller.full_list[int(code)]['visible'] = 0
        dm.save_codes_json(self.controller.full_list)
        self.current_button.destroy()

    def get_cover_url_sync(self, code_int):
        future = asyncio.run_coroutine_threadsafe(
            self.controller.cover_loader.load_cover_image_if_needed(code_int),
            self.controller.loop
        )
        return future.result()

    def apply_filter(self):
        """
        Convert user query into a list of tag IDs and store them in self.search_filter.
        """
        query = self.filter_entry.get().lower()
        if query:
            matched_tags = {
                key: value
                for key, value in self.controller.tags.items()
                if query in value.lower()
            }
            self.search_filter = list(matched_tags.keys())          
        else:
            self.search_filter = []
        self.update_page()

    def clear_filter(self):
        """Clear the search filter and refresh codes."""
        self.search_filter = []
        self.filter_entry.delete(0, tk.END)
        self.update_page()

    def toggle_image_load(self):
        """Enable/disable image loading globally."""
        self.controller.settings['images'] = self.image_var.get()
        dm.write_settings(self.controller.settings)
        self.controller.update_all_pages()

    def refresh_codes(self):
        """Simulate re-fetching images for the currently displayed codes."""
        self.refresh_button.config(state="disabled")
        self.loading_label.config(text="Loading images, please wait...")
        self.update_page()
        self.refresh_button.config(state="normal")
        self.loading_label.config(text="")

    def open_code(self, code):
        """Open the code in a private browser tab and switch to the Home page."""
        open_in_browser(code)
        home_page = self.controller.get_page(0)
        home_page.show_section()
        home_page.code_progress_entry.delete(0, tk.END)
        home_page.code_progress_entry.insert(0, code)
        self.controller.notebook.select(home_page)

    def update_page(self):
        """Grab a few random codes (filtered if needed) and display them."""
        for widget in self.code_buttons_frame.winfo_children():
            widget.destroy()

        # If user is filtering by certain tags, reduce to those codes
        if self.search_filter:
            filtered_codes = []
            for c in self.controller.master_list.keys():
                tags_set = self.controller.master_list[c]['tags']
                if any(tid in tags_set for tid in self.search_filter):
                    filtered_codes.append(c)
        else:
            filtered_codes = list(self.controller.master_list.keys())

        if not filtered_codes:
            self.loading_label.config(text="No codes match your filter!")
            return

        selected_codes = random.sample(filtered_codes, min(6, len(filtered_codes)))
        self.images = []

        # For each code, fetch cover URL from background loop, then load the image sync
        for code_val in selected_codes:
            cover_url = self.controller.full_list.get(code_val, {}).get('cover')
            if cover_url is None or cover_url == "":
                cover_url = self.get_cover_url_sync(code_val)
                self.controller.full_list[code_val]['cover'] = cover_url
                
            image_path = os.path.join(COVERS_DIR, f"{code_val}.jpg")
            if os.path.exists(image_path):
                img = Image.open(image_path).resize((self.button_width, self.button_height))
                photo_img = ImageTk.PhotoImage(img)
                
            else:
                photo_img = load_cover_image_sync(
                    cover_url,
                    size=(self.button_width, self.button_height),
                    load_images=self.controller.settings['images']
                )
            self.images.append(photo_img)

        # Grid config
        for row in range(2):
            self.code_buttons_frame.rowconfigure(row, weight=0, minsize=self.button_height)
        for col in range(3):
            self.code_buttons_frame.columnconfigure(col, weight=0, minsize=self.button_width)
            

        # Create buttons
        for idx, code_val in enumerate(selected_codes):
            row = idx // 3
            col = idx % 3
            button = tk.Button(
                self.code_buttons_frame,
                text=str(code_val),
                image=self.images[idx],
                compound="center",
                font=(self.controller.settings["theme"]["font_family"], self.controller.settings["theme"]["font_size"]),
                width=10,
                height=8,
                command=lambda val=code_val: self.open_code(val)
            )
            button.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
            # Right-click binding
            button.bind("<Button-3>", self.show_popup)
            # Store code on the button so we can retrieve it easily
            button.code_val = code_val

        self.loading_label.config(text="")
        self.controller.adjust_window_size()


class PageTwo(ttk.Frame):
    """
    Page for displaying Favorites with basic name/tag filtering and pagination.
    """
    def __init__(self, parent, notebook, controller):
        super().__init__(parent)
        self.notebook = notebook
        self.controller = controller

        self.items_per_page = 12
        self.current_page = 0

        # --- UI: Search / Sort bar ---
        self.search_sort_frame = ttk.Frame(self)
        self.search_sort_frame.pack(pady=5, fill="x")

        # Name filter
        ttk.Label(self.search_sort_frame, text="Name:").pack(side=tk.LEFT, padx=5)
        self.name_search_entry = ttk.Entry(self.search_sort_frame, width=20)
        self.name_search_entry.pack(side=tk.LEFT, padx=5)
        self.name_search_entry.bind("<Return>", lambda e: self.apply_filters())

        # Tag filter
        ttk.Label(self.search_sort_frame, text="Tag(s):").pack(side=tk.LEFT, padx=5)
        self.tag_filter_entry = ttk.Entry(self.search_sort_frame, width=15)
        self.tag_filter_entry.pack(side=tk.LEFT, padx=5)
        self.tag_filter_entry.bind("<Return>", lambda e: self.apply_filters())

        # Folder filter
        ttk.Label(self.search_sort_frame, text="Folder:").pack(side=tk.LEFT, padx=5)
        self.folder_filter_entry = ttk.Entry(self.search_sort_frame, width=15)
        self.folder_filter_entry.pack(side=tk.LEFT, padx=5)
        self.folder_filter_entry.bind("<Return>", lambda e: self.apply_filters())

        # Sort preference
        ttk.Label(self.search_sort_frame, text="Sort:").pack(side=tk.LEFT, padx=5)
        self.sort_combobox = ttk.Combobox(
            self.search_sort_frame,
            values=["Alphabetical", "Random"],
            state="readonly",
            width=12
        )
        self.sort_combobox.pack(side=tk.LEFT, padx=5)
        self.sort_combobox.set("Alphabetical")

        self.search_button = ttk.Button(
            self.search_sort_frame, text="Search", command=self.apply_filters
        )
        self.search_button.pack(side=tk.LEFT, padx=5)

        # --- Main items frame + pagination ---
        self.items_frame = ttk.Frame(self)
        self.items_frame.pack(pady=10)

        self.nav_frame = ttk.Frame(self)
        self.nav_frame.pack(pady=10)

        self.prev_button = ttk.Button(self.nav_frame, text="Previous", command=self.prev_page)
        self.prev_button.pack(side=tk.LEFT, padx=10)

        self.next_button = ttk.Button(self.nav_frame, text="Next", command=self.next_page)
        self.next_button.pack(side=tk.LEFT, padx=10)
        
        # Right-click menu for code items
        self.current_button = None
        self.popup_menu = tk.Menu(self, tearoff=0)
        self.add_menu = tk.Menu(self.popup_menu, tearoff=0)

        # This list holds either ("folder", folder_name) or ("code", code_val).
        self.display_list = []

        self.apply_filters()

    def apply_filters(self):
        """Load favorites, filter by name/tag, then sort by user preference."""
        self.favorites_dict = dm.load_favorite_json()

        # Grab filter inputs
        name_query = self.name_search_entry.get().strip().lower()
        tag_query = self.tag_filter_entry.get().strip().lower()
        folder_query = self.folder_filter_entry.get().strip().lower()
        sort_pref = self.sort_combobox.get()

        # Convert comma-separated tag strings to tag IDs
        tag_ids_to_filter = []
        if tag_query:
            for tag_part in tag_query.split(","):
                tag_part = tag_part.strip().lower()
                try:
                    tag_ids_to_filter.append(int(tag_part))
                except ValueError:
                    tag_ids_to_filter.extend(self.find_tag_id(tag_part))

        # We'll build a "raw" list, then sort it
        combined_items = []
        self.folders = []

        for code_val, fav_entry in self.favorites_dict.items():
            if not fav_entry or not isinstance(fav_entry, dict):
                continue

            # Basic info
            name_val = str(fav_entry.get("name", ""))
            folder_val = str(fav_entry.get("folder", "") or "")
            folder_lower = folder_val.lower()
            code_tags = set(fav_entry.get("tags", []))

            # Check filters
            match_name = (name_query in name_val.lower()) if name_query else True
            # For folder filtering, if folder_query is empty, we don't use it as a gate to hide codes.
            # But if folder_query is present, we only want codes that match it.
            match_folder = True
            if folder_query:
                # If user typed a folder filter, only show codes that have that folder
                match_folder = (folder_query in folder_lower)
            else:
                # If user left folder filter blank, we do not necessarily hide items by folder.
                # We'll handle logic below on how to show/hide foldered codes.
                pass

            # Tag match
            if tag_ids_to_filter:
                match_tags = any(tid in code_tags for tid in tag_ids_to_filter)
            else:
                match_tags = True

            if not (match_name and match_folder and match_tags):
                # This item doesn't match all filters -> skip
                continue

            # ----------------------------------
            # Decide what to add to display_list:
            # - If the folder filter is blank, we only show folder BUTTONS (not codes) 
            #   if they actually have a folder, 
            #   and show code if it's un-foldered
            #
            # - If the folder filter is set, we show only codes from that folder.
            # ----------------------------------

            if folder_query == "":
                # 1) If this code has a folder, we do NOT add it as ("code", code_val).
                #    Instead, we add one folder button for that folder. 
                #    But we must ensure not to add duplicates of the same folder.
                if folder_val.strip():
                    # We'll store it as ("folder", folder_val), but avoid duplicates
                    # by only adding if it's not already in combined_items.
                    # (We can also handle duplicates by building a set of folder names first.)
                    already_has = any(
                        (it[0] == "folder" and it[1].lower() == folder_val.lower())
                        for it in combined_items
                    )
                    if not already_has:
                        combined_items.append(("folder", folder_val, code_val))
                        self.folders.append(folder_val)
                else:
                    # 2) If there's no folder, this is un-foldered => show the code
                    combined_items.append(("code", code_val, 0))

            else:
                # The user typed a folder filter => we only show codes that match that folder
                # So, if code_val is indeed in the folder, show it
                if folder_val.strip():
                    # Show the actual code now
                    combined_items.append(("code", code_val, 0))
                else:
                    # If it's un-foldered, it doesn't belong to that folder
                    pass

        # ---------- Sorting ----------
        if sort_pref == "Alphabetical":
            def sort_key(item):
                if item[0] == "folder":
                    # Sort by folder name
                    return item[1].lower()
                else:
                    # item == ("code", code_val)
                    c_val = item[1]
                    return self.favorites_dict[c_val]["name"].lower()
            combined_items.sort(key=sort_key)

        elif sort_pref == "Random":
            random.shuffle(combined_items)

        self.display_list = combined_items
        self.current_page = 0
        self.update_page()

    def update_page(self):
        """Show the current page of favorite items."""
        for widget in self.items_frame.winfo_children():
            widget.destroy()

        start_index = self.current_page * self.items_per_page
        end_index = start_index + self.items_per_page
        page_items = self.display_list[start_index:end_index]

        # Decide button size
        if self.controller.settings['images']:
            btn_height = 150
            btn_width = 100
        else:
            btn_height = 8
            btn_width = 10

        self.images = []
        cols = 6
        row = 0
        col = 0

        for item_type, value, first in page_items:
            if item_type == "folder":
                # Show a folder button
                folder_frame = ttk.Frame(self.items_frame)
                folder_frame.grid(row=row, column=col, padx=10, pady=5, sticky="nsew")
                
                label_text = "GROUP: " + value
                label = ttk.Label(folder_frame, text=label_text, wraplength=100, justify="center")
                
                
                image_path = os.path.join(COVERS_DIR, f"{first}.jpg")
                img = Image.open(image_path).resize((100, 150))
                photo_img = ImageTk.PhotoImage(img)

                folder_name = value
                folder_btn = tk.Button(
                    folder_frame,
                    image=photo_img,
                    width=btn_width,
                    height=btn_height,
                    command=lambda fn=folder_name: self.show_only_that_folder(fn)
                )
                folder_btn.pack()
                label.pack(pady=(0, 10))
                
                self.images.append(photo_img)

                col += 1
                if col >= cols:
                    row += 1
                    col = 0

            else:
                # item_type == "code"
                code_val = value
                # Ensure the code is in self.controller.full_list
                if code_val not in self.controller.full_list:
                    self.controller.full_list[code_val] = {"tags": [], "cover": "", "visible": 1}

                cover_url = self.controller.full_list[code_val].get("cover") or None
                image_path = os.path.join(COVERS_DIR, f"{code_val}.jpg")
                if os.path.exists(image_path):
                    img = Image.open(image_path).resize((100, 150))
                    photo_img = ImageTk.PhotoImage(img)
                else:
                    photo_img = load_cover_image_sync(
                        cover_url,
                        size=(100, 150),
                        load_images=self.controller.settings['images']
                    )

                self.images.append(photo_img)

                item_frame = ttk.Frame(self.items_frame)
                item_frame.grid(row=row, column=col, padx=10, pady=0, sticky="nsew")

                label_text = self.favorites_dict[code_val]['name']
                label = ttk.Label(item_frame, text=label_text, wraplength=100, justify="center")

                button = tk.Button(
                    item_frame,
                    image=photo_img,
                    width=btn_width,
                    height=btn_height,
                    command=lambda val=code_val: self.open_code(val)
                )
                button.pack()
                label.pack(pady=(0, 10))

                # Right-click binding
                button.bind("<Button-3>", self.show_popup)
                button.code_val = code_val

                col += 1
                if col >= cols:
                    row += 1
                    col = 0

        # Pagination controls
        self.prev_button.config(state=tk.NORMAL if self.current_page > 0 else tk.DISABLED)
        next_disabled = (self.current_page + 1) * self.items_per_page >= len(self.display_list)
        self.next_button.config(state=tk.NORMAL if not next_disabled else tk.DISABLED)

    def next_page(self):
        self.current_page += 1
        self.update_page()

    def prev_page(self):
        self.current_page -= 1
        self.update_page()

    def open_code(self, code):
        open_in_browser(code)
        home_page = self.controller.get_page(0)
        self.controller.notebook.select(home_page)
        
    def show_only_that_folder(self, folder_name):
        """
        Replace the folder filter with the chosen folder name,
        so we display codes that have that folder.
        """
        self.folder_filter_entry.delete(0, tk.END)
        self.folder_filter_entry.insert(0, folder_name)
        self.apply_filters()

    def show_popup(self, event):
        """
        Right-click context menu for code items:
         - We'll rebuild the popup menu each time, so we can decide if "Remove from folder" is needed.
        """
        self.current_button = event.widget
        code = getattr(self.current_button, 'code_val', None)

        # Clear old menu items
        self.popup_menu.delete(0, tk.END)
        self.add_menu.delete(0, tk.END)

        # Common items
        self.popup_menu.add_command(label="Remove from favorites", command=self.discard)
        
        self.add_menu.add_command(label = "Create Group", command = self.create_folder)        
        for folder in self.folders:
            self.add_menu.add_command(label = f"{folder}", command = lambda f = folder: self.add_to_folder(f))
            
        self.popup_menu.add_cascade(label = "Add to Group", menu = self.add_menu)

        # If this code is actually in a folder, show "Remove from folder" option
        if code:
            fav_dict = dm.load_favorite_json()
            if code in fav_dict:
                folder_name = fav_dict[code].get("folder", "")
                if folder_name != None:
                    if folder_name.strip():
                        # The code is in a folder, so let's allow removal
                        self.popup_menu.add_command(label="Remove from folder", command=self.remove_from_folder)

        self.popup_menu.tk_popup(event.x_root, event.y_root)
        
    def create_folder(self):
        """
        Prompt the user to move the selected code to a different folder.
        """
        if self.current_button is None:
            return
        code = getattr(self.current_button, 'code_val', None)
        if code is None:
            return

        new_folder = simpledialog.askstring("Move to Folder", "Enter new folder name:")
        if new_folder is not None:
            self.favorites_dict[code]["folder"] = new_folder
            dm.save_favorites_json(self.favorites_dict)
            self.apply_filters()
            
    def remove_from_folder(self):
        """
        Set folder to "" for this code and re-save.
        """
        if not self.current_button:
            return
        code = getattr(self.current_button, 'code_val', None)
        if not code:
            return

        fav_dict = dm.load_favorite_json()
        if code in fav_dict:
            fav_dict[code]["folder"] = ""  # Clear the folder
            dm.save_favorites_json(fav_dict)

        self.apply_filters()
        
    def add_to_folder(self, new_folder):
        if self.current_button is None:
            return
        code = getattr(self.current_button, 'code_val', None)
        if code is None:
            return
        
        if new_folder is not None:
            self.favorites_dict[code]["folder"] = new_folder
            dm.save_favorites_json(self.favorites_dict)
            self.apply_filters()

    def discard(self):
        """
        Remove selected code from favorites.
        """
        if self.current_button is None:
            return
        code = getattr(self.current_button, 'code_val', None)
        if code is None:
            return

        fav_dict = dm.load_favorite_json()
        if code in fav_dict:
            del fav_dict[code]
            dm.save_favorites_json(fav_dict)

        # Re-apply filters
        self.apply_filters()

    def find_tag_id(self, tag_input):
        """
        Return a list of tag IDs whose tag name contains `tag_input`.
        """
        all_tags = self.controller.tags
        return [tag_id for tag_id, tag_name in all_tags.items() if tag_input in tag_name.lower()]


class PageThree(ttk.Frame):
    """
    Page to handle the 'sauce list updater':
    - Banning/unbanning tags
    - Scraping new codes
    - Updating existing list
    """
    def __init__(self, parent, notebook, controller):
        super().__init__(parent)
        self.notebook = notebook
        self.controller = controller

        self.items_per_page = 24
        self.current_page = 0

        # Frames
        self.banned_frame = ttk.Frame(self, borderwidth=2, relief='ridge')
        self.banned_labels_frame = ttk.Frame(self.banned_frame)
        self.search_frame = ttk.Frame(self)
        self.items_frame = ttk.Frame(self)

        self.banned_frame.pack(pady=5, fill='x')
        self.banned_labels_frame.pack(side=tk.TOP, pady=10, fill='x')
        self.search_frame.pack(pady=(15, 5), fill='x')
        self.items_frame.pack(pady=10)

        # Navigation frame
        self.nav_frame = ttk.Frame(self)
        self.nav_frame.pack(pady=10, fill="x")

        self.prev_button = ttk.Button(self.nav_frame, text="Previous", command=self.prev_page)
        self.prev_button.grid(row=0, column=0, padx=10, pady=10)
        self.next_button = ttk.Button(self.nav_frame, text="Next", command=self.next_page)
        self.next_button.grid(row=0, column=1, padx=10, pady=10)

        self.tag_update_button = ttk.Button(self.nav_frame, text="Update tags", command=self.start_tag_fetch)
        self.tag_update_button.grid(row=0, column=5, padx=10, pady=10)

        # For searching tags
        self.search_entry = ttk.Entry(self.search_frame, width=30)
        self.search_entry.pack(side=tk.LEFT, padx=5)
        self.search_entry.bind("<Return>", lambda event: self.search_tags())

        self.search_button = ttk.Button(self.search_frame, text="Search", command=self.search_tags)
        self.search_button.pack(side=tk.LEFT, padx=5)

        # Banned tags
        self.banned_tag_codes = self.controller.settings['banned']['tags']
        # Convert numeric IDs -> names for display
        self.banned_tag_names = [self.controller.tags.get(code, str(code)) for code in self.banned_tag_codes]

        # Hide banned label checkbox
        self.hide_banned = tk.BooleanVar(value=False)
        self.hide_banned_checkbox = ttk.Checkbutton(
            self.banned_frame,
            text="Hide Banned Label",
            variable=self.hide_banned,
            command=self.toggle_banned_label
        )
        self.hide_banned_checkbox.pack(side=tk.LEFT, padx=10)

        # Banned tags display
        self.banned_title = ttk.Label(self.banned_labels_frame, text="Banned Tags:")
        self.banned_label = ttk.Label(self.banned_labels_frame, text=" ")
        self.banned_title.pack(side=tk.LEFT, padx=5)
        self.banned_label.pack(side=tk.LEFT, padx=5)

        # Progress / scraping
        self.scrape_progress = 0
        self.scrape_done = False
        self.scrape_max = 1

        # Buttons to generate or update the list
        self.generate_list_button = ttk.Button(
            self.banned_frame,
            text="Generarate List",
            command=lambda: self.code_generate_async(update=1)
        )
        self.generate_list_button.pack(side=tk.LEFT, padx=10)

        self.update_list_button = ttk.Button(
            self.banned_frame,
            text="Update List",
            command=lambda: self.code_add_async(update=1)
        )
        self.update_list_button.pack(side=tk.LEFT, padx=10)

        # Current tags for display
        self.filtered_tags = self.controller.tags
        self.update_page()

    def start_tag_fetch(self):
        """Spawn a progress popup for tag fetching."""
        self.progress_window = Toplevel(self)
        self.progress_window.title("Fetching Tags")
        self.progress_window.geometry("400x100")

        label = ttk.Label(self.progress_window, text="Fetching tags, please wait...")
        label.pack(pady=10)

        self.progress_bar = Progressbar(self.progress_window, length=300, mode="indeterminate")
        self.progress_bar.pack(pady=5)
        self.progress_bar.start()

        # Instead of asyncio.run, we schedule coroutines in the background loop
        def run_tag_fetch():
            future = asyncio.run_coroutine_threadsafe(self.fetch_tags(), self.controller.loop)
            future.result()

        threading.Thread(target=run_tag_fetch, daemon=True).start()

    async def fetch_tags(self):
        """Call the async tag_fetch from TagFinder."""
        try:
            await tag_fetch()
            logging.info("Tag fetching completed.")
        except Exception as e:
            logging.error(f"Error during tag fetching: {e}")
        finally:
            self.progress_bar.stop()
            self.progress_window.destroy()

            # Reload tags after fetching
            self.controller.tags = dm.read_tags()
            self.filtered_tags = self.controller.tags
            self.update_page()

    def toggle_banned_label(self):
        """Show or hide the Banned Tags label."""
        if self.hide_banned.get():
            self.banned_title.pack_forget()
            self.banned_label.pack_forget()
        else:
            self.banned_title.pack(side=tk.LEFT, padx=5)
            self.banned_label.pack(side=tk.LEFT, padx=5)

    def code_generate_async(self, update):
        """Full generation of new codes from scratch (with banned tags)."""
        self._show_scrape_popup("Scraping in progress...", self._scrape_async, update)

    def code_add_async(self, update):
        """Update codes incrementally (adding anything new since last max code)."""
        self._show_scrape_popup("Scraping in progress...", self.update_scrape_async, update)

    def _show_scrape_popup(self, title, scrape_func, update):
        """Generic method to show a scraping progress popup and run a function in background."""
        self.progress_window = Toplevel(self)
        self.progress_window.title("Scraping Progress")
        self.progress_window.geometry("400x100")

        label = ttk.Label(self.progress_window, text=title)
        label.pack(pady=10)

        self.progress_bar = Progressbar(self.progress_window, length=300, mode="determinate")
        self.progress_bar.pack(pady=5)

        def run_in_bg():
            # Instead of asyncio.run, schedule in background loop
            future = asyncio.run_coroutine_threadsafe(scrape_func(update), self.controller.loop)
            future.result()

        threading.Thread(target=run_in_bg, daemon=True).start()
        self._check_scrape_progress()

    def _check_scrape_progress(self):
        """Repeatedly poll for scraping progress."""
        self.progress_bar["maximum"] = self.scrape_max
        self.progress_bar["value"] = self.scrape_progress
        if not self.scrape_done:
            self.after(200, self._check_scrape_progress)
        else:
            self.progress_window.destroy()
            # Reload data
            self.controller.full_list = dm.load_codes_json()
            self.controller.master_list = {
                k: v for k, v in self.controller.full_list.items() if v.get('visible') == 1
            }
            logging.info("Scraping completed and data reloaded.")
            self.controller.update_all_pages()

    async def _scrape_async(self, update):
        """
        Full scraping from page 1..N (English, minus banned tags), 
        saving new codes, covers, etc. 
        Uses the shared CoverLoader for cover URLs.
        """
        url_base = "https://nhentai.net/search/?q=english"
        for tag_name in self.banned_tag_names:
            url_base += f"+-{tag_name}"
        url_first = f"{url_base}&page=1"

        try:
            first_resp = await asyncio.to_thread(requests.get, url_first, proxies=PROXIES, timeout=TIMEOUT)
            first_resp.raise_for_status()
        except Exception as e:
            logging.error(f"Error fetching first page: {e}")
            self.scrape_max = 1
            self.scrape_done = True
            return

        soup_first = BeautifulSoup(first_resp.text, "html.parser")
        last_link = soup_first.find("a", class_="last")
        if not last_link:
            logging.warning("Could not find last-page link. Defaulting to 1.")
            last_page = 1
        else:
            try:
                last_page = int(last_link.get("href").split("=")[-1])
            except (ValueError, AttributeError):
                logging.warning("Failed to parse last-page number. Defaulting to 1.")
                last_page = 1

        self.scrape_max = last_page
        logging.info(f"Determined last_page={last_page} from the search results.")

        # Step 2: Loop pages
        for page_idx in range(1, last_page + 1):
            page_url = f"{url_base}&page={page_idx}"
            if page_idx % 100 == 0:
                logging.info(f"On page {page_idx}")

            try:
                resp = await asyncio.to_thread(requests.get, page_url, proxies=PROXIES, timeout=TIMEOUT)
                resp.raise_for_status()
            except Exception as e:
                logging.error(f"Error scraping page {page_idx}: {e}")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            comics = soup.find_all("div", class_="gallery")

            if not comics:
                logging.info(f"No galleries found on page {page_idx}. Stopping early.")
                break

            for comic in comics:
                tag_strs = comic.get("data-tags", "").split()
                try:
                    tag_ids = set(int(t) for t in tag_strs)
                except ValueError:
                    tag_ids = set()

                link_a = comic.find("a")
                if not link_a:
                    continue

                code_link = link_a.get("href", "")
                if code_link.startswith("/g/") and code_link.endswith("/"):
                    try:
                        code_val = int(code_link[3:-1])
                    except ValueError:
                        continue

                    # If new, fetch cover
                    if code_val not in self.controller.full_list:
                        cover_url = await self.controller.cover_loader.load_cover_image_if_needed(code_val)
                        self.controller.full_list[code_val] = {
                            'tags': tag_ids,
                            'cover': cover_url,
                            'visible': 1
                        }
                    else:
                        # If it existed, maybe update tags / cover
                        self.controller.full_list[code_val]['tags'] = tag_ids
                        if not self.controller.full_list[code_val].get('cover'):
                            cover_url = await self.controller.cover_loader.load_cover_image_if_needed(code_val)
                            self.controller.full_list[code_val]['cover'] = cover_url

            self.scrape_progress = page_idx
            await asyncio.sleep(0)

        dm.save_codes_json(self.controller.full_list)
        self.scrape_done = True
        logging.info("Scraping completed successfully.")

    async def update_scrape_async(self, update):
        """
        Incremental update: stops when code_val < last_code.
        Uses the shared CoverLoader as well.
        """
        url_base = "https://nhentai.net/search/?q=english"
        for tag_name in self.banned_tag_names:
            url_base += f'+-{tag_name}'
        url_first = f"{url_base}&page=1"

        all_codes = self.controller.full_list.keys()
        last_code = max(all_codes) if all_codes else 0

        try:
            first_resp = await asyncio.to_thread(requests.get, url_first, proxies=PROXIES, timeout=TIMEOUT)
            first_resp.raise_for_status()
        except Exception as e:
            logging.error(f"Error fetching first page: {e}")
            self.scrape_max = 1
            self.scrape_done = True
            return

        soup_first = BeautifulSoup(first_resp.text, "html.parser")
        last_link = soup_first.find("a", class_="last")
        if not last_link:
            logging.warning("Could not find last-page link. Defaulting to 1.")
            last_page = 1
        else:
            try:
                last_page = int(last_link.get("href").split("=")[-1])
            except (ValueError, AttributeError):
                logging.warning("Failed to parse last-page number. Defaulting to 1.")
                last_page = 1

        self.scrape_max = max(last_code, 1)
        logging.info(f"Determined last_code={last_code} from existing data.")

        for page_idx in range(1, last_page + 1):
            url = f"{url_base}&page={page_idx}"
            try:
                resp = await asyncio.to_thread(requests.get, url, proxies=PROXIES, timeout=TIMEOUT)
                resp.raise_for_status()
            except Exception as e:
                logging.error(f"Error scraping page {page_idx}: {e}")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            comics = soup.find_all("div", class_="gallery")
            if not comics:
                logging.info(f"No galleries found on page {page_idx}. Stopping early.")
                break

            for comic in comics:
                tag_strs = comic.get("data-tags", "").split()
                try:
                    tag_ids = set(int(t) for t in tag_strs)
                except ValueError:
                    tag_ids = set()

                link_a = comic.find("a")
                if not link_a:
                    continue
                code_link = link_a.get("href", "")
                if code_link.startswith("/g/") and code_link.endswith("/"):
                    try:
                        code_val = int(code_link[3:-1])
                    except ValueError:
                        continue

                    # If we see code_val < last_code, break
                    if code_val < last_code:
                        break

                    if code_val not in self.controller.full_list:
                        cover_url = await self.controller.cover_loader.load_cover_image_if_needed(code_val)
                        self.controller.full_list[code_val] = {
                            'tags': tag_ids,
                            'cover': cover_url,
                            'visible': 1
                        }
                    else:
                        self.controller.full_list[code_val]['tags'] = tag_ids
                        if not self.controller.full_list[code_val].get('cover'):
                            cover_url = await self.controller.cover_loader.load_cover_image_if_needed(code_val)
                            self.controller.full_list[code_val]['cover'] = cover_url

            if code_val < last_code:
                break

            self.scrape_progress = code_val - last_code
            await asyncio.sleep(0)

        dm.save_codes_json(self.controller.full_list)
        self.scrape_done = True
        logging.info("Scraping completed successfully.")

    def update_page(self):
        """Refresh the UI with current banned tags, current tag listing, etc."""
        # Update label
        self.banned_label.config(text=self.banned_tag_names)
        self.banned_label.update_idletasks()
        self.banned_label.config(wraplength=self.winfo_width() - 50)

        for widget in self.items_frame.winfo_children():
            widget.destroy()

        start_index = self.current_page * self.items_per_page
        end_index = start_index + self.items_per_page
        page_items = list(self.filtered_tags.items())[start_index:end_index]

        cols = 4
        for idx, (tag_code, tag_name) in enumerate(page_items):
            r = idx // cols
            c = idx % cols
            button = tk.Button(
                self.items_frame,
                text=str(tag_name),
                compound="center",
                font=(self.controller.settings["theme"]["font_family"], self.controller.settings["theme"]["font_size"]),
                command=lambda code=tag_code, name=tag_name: self.ban_tag((code, name))
            )
            button.grid(row=r, column=c, padx=10, pady=10, sticky="nsew")

        # Pagination
        self.prev_button.config(state=tk.NORMAL if self.current_page > 0 else tk.DISABLED)
        can_next = (self.current_page + 1) * self.items_per_page < len(self.filtered_tags)
        self.next_button.config(state=tk.NORMAL if can_next else tk.DISABLED)

        self.controller.adjust_window_size()

    def next_page(self):
        self.current_page += 1
        self.update_page()

    def prev_page(self):
        self.current_page -= 1
        self.update_page()

    def ban_tag(self, tag):
        """
        Toggle ban/unban of the given tag.
        """
        tag_code, tag_name = tag
        if tag_code not in self.banned_tag_codes:
            self.banned_tag_codes.append(tag_code)
            self.banned_tag_names.append(tag_name)
            self.controller.settings['banned']['tags'].append(tag_code)
        else:
            self.banned_tag_codes.remove(tag_code)
            self.banned_tag_names.remove(tag_name)
            self.controller.settings['banned']['tags'].remove(tag_code)

        dm.write_settings(self.controller.settings)

        # If search is empty, reset back to full tag list
        if not self.search_entry.get().strip():
            self._reset_search()
        self.update_page()

    def search_tags(self):
        """Filter the displayed tags by the search query."""
        query = self.search_entry.get().lower()
        if query:
            self.filtered_tags = {
                key: value
                for key, value in self.controller.tags.items()
                if query in value.lower()
            }
        else:
            self.filtered_tags = self.controller.tags
        self.current_page = 0
        self.update_page()

    def _reset_search(self):
        self.search_entry.delete(0, tk.END)
        self.filtered_tags = self.controller.tags
        self.update_page()


class PageFour(ttk.Frame):
    """
    Statistics page showing basic counts of usable codes, favorites, etc.
    """
    def __init__(self, parent, notebook, controller):
        super().__init__(parent)
        self.notebook = notebook
        self.controller = controller

        ttk.Label(self, text="Statistics", font=(self.controller.settings["theme"]["font_family"], 16)).pack(pady=10)
        self.usable_codes_label = ttk.Label(self, text="Usable Codes: 0")
        self.usable_codes_label.pack(pady=5)

        self.in_progress_label = ttk.Label(self, text="In Progress: 0")
        self.in_progress_label.pack(pady=5)

        self.favorites_label = ttk.Label(self, text="Favorites: 0")
        self.favorites_label.pack(pady=5)

        self.tags_label = ttk.Label(self, text="Tags: 0")
        self.tags_label.pack(pady=5)

        self.banned_label = ttk.Label(self, text="Banned Tags: 0")
        self.banned_label.pack(pady=5)

        ttk.Button(self, text="Refresh Stats", command=self.update_page).pack(pady=15)

        self.update_page()

    def update_page(self):
        usable_codes = code_read()
        self.usable_codes_label.config(text=f"Usable Codes: {len(usable_codes)}")

        in_progress_count = len(self.controller.settings['in_progress'])
        self.in_progress_label.config(text=f"In Progress: {in_progress_count}")

        favorites = dm.load_favorite_json()
        self.favorites_label.config(text=f"Favorites: {len(favorites)}")

        tags_list = dm.read_tags()
        self.tags_label.config(text=f"Tags: {len(tags_list)}")

        banned = self.controller.settings['banned']['tags']
        self.banned_label.config(text=f"Banned Tags: {len(banned)}")

        self.controller.adjust_window_size()


# --------------------
# Main Execution
# --------------------

if __name__ == "__main__":
    # Ensure the directories exist
    os.makedirs(app_settings["paths"]["info_directory"], exist_ok=True)
    os.makedirs(app_settings["paths"]["covers_directory"], exist_ok=True)

    app = MultiPageApp()
    app.mainloop()
