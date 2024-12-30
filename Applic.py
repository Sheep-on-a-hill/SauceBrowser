import ast
import os
import random
import subprocess
import tkinter as tk
from tkinter import ttk
from ttkthemes import ThemedTk

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageTk

import logging
from tkinter import Toplevel
from tkinter.ttk import Progressbar
import asyncio
import threading

# Import your data manager
import data_manager_json as dm
from TagFinder import tag_fetch


# --------------------
# Constants & Helpers
# --------------------

INFO_DIR = dm.INFO_DIR
COVERS_DIR = dm.COVERS_DIR

# Initialize logging AFTER reading settings so we can use log_file from user config
app_settings = dm.load_settings()
log_file_path = app_settings["paths"]["log_file"]
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
logging.basicConfig(
    filename=log_file_path,  # log to user-specified file
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

TAGS_FILE = os.path.join(INFO_DIR, "tags.txt")


def get_name(code):
    """
    Example: Wrap requests in retry logic & proxy usage from settings['network'].
    """
    net_cfg = app_settings["network"]
    proxies = {"http": net_cfg["proxy"], "https": net_cfg["proxy"]} if net_cfg["proxy"] else None
    
    url = f'https://nhentai.net/g/{code}/'
    # Simple retry logic
    for attempt in range(net_cfg["retry_attempts"]):
        try:
            response = requests.get(url, timeout=net_cfg["timeout"], proxies=proxies)
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, "html.parser")
                name_tag = soup.find('span', class_='pretty')
                name = name_tag.text if name_tag else "Unknown Name"
                return name
            else:
                logging.warning(f"Failed to fetch {url} with status {response.status_code}")
        except Exception as e:
            logging.error(f"Request attempt {attempt+1} failed: {e}")
    return "Unknown Name"

def get_tags(banned_tags):
    """Run a subprocess to get tags from 'TagTest.py' with given banned tags."""
    subprocess.run(["python", "TagTest.py", banned_tags])


def scrape_images(code, output_folder):
    """
    Example: Use network config for scraping the cover as well.
    """
    net_cfg = app_settings["network"]
    proxies = {"http": net_cfg["proxy"], "https": net_cfg["proxy"]} if net_cfg["proxy"] else None

    url = f"https://nhentai.net/g/{code}/"
    image_path = os.path.join(output_folder, f"{code}.jpg")
    if os.path.exists(image_path):
        return None

    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # Wrap in retries
    for attempt in range(net_cfg["retry_attempts"]):
        try:
            response = requests.get(url, timeout=net_cfg["timeout"], proxies=proxies)
            if response.status_code != 200:
                logging.warning(f"Failed to fetch {url}")
                return

            soup = BeautifulSoup(response.content, "html.parser")
            img_tags = soup.find_all("img")
            if len(img_tags) < 2:
                logging.warning(f"No suitable images found for code {code}")
                return

            img_tag = img_tags[1]
            img_url = (
                img_tag.get("data-src")
                or img_tag.get("data-lazy-src")
                or img_tag.get("data-original")
                or img_tag.get("src")
            )

            if not img_url.startswith("http"):
                img_url = requests.compat.urljoin(url, img_url)

            img_data = requests.get(img_url, timeout=net_cfg["timeout"], proxies=proxies).content
            with open(image_path, "wb") as img_file:
                img_file.write(img_data)
            logging.info(f"Downloaded cover for code {code} -> {image_path}")
            return
        except Exception as e:
            logging.error(f"Attempt {attempt+1}: Failed to download {url}: {e}")
    # If all attempts fail, do nothing.


def code_read():
    """Return a dict {code: set_of_tags} from JSON."""
    return dm.load_codes_json()



# --------------------
# Application Classes
# --------------------

class MultiPageApp:
    """
    Main application window containing a notebook with multiple pages.
    """

    def __init__(self):
        self.settings = dm.load_settings()
        
        # -- Adjust the Data & Logging directories if you'd like:
        global INFO_DIR
        INFO_DIR = self.settings["paths"]["info_directory"]
        os.makedirs(INFO_DIR, exist_ok=True)
        
        # -- Initialize ThemedTk with the user-chosen theme --
        self.root = ThemedTk(theme=self.settings["theme"]["name"])
        
        # fallback if not specified in settings
        default_size = self.settings["app"].get("window_size", "400x510")
        self.root.geometry(default_size)

        # Example: set a custom font
        font_family = self.settings["theme"]["font_family"]
        font_size = self.settings["theme"]["font_size"]
        
        # to globally set fonts
        self.style = ttk.Style(self.root)
        self.style.configure(".", font=(font_family, font_size))
        
        self.root.title("Sauce Selector")

        # Show a loading label
        self.loading_label = ttk.Label(self.root, text="Loading data, please wait...")
        self.loading_label.pack(pady=50)

        self.full_list = dm.load_codes_json()
        self.master_list = {
            key: value for key, value in self.full_list.items() if value.get('visible') == 1
        }

        self.current_theme = self.settings['theme']['name']
        
        # Start a background load
        threading.Thread(target=self.load_data_async, args=(self.master_list,)).start()
        
    def list_update(self, codes_dict):
        """
        Save updated dictionary of codes.
        """
        self.master_list = {
            key: value for key, value in self.full_list.items() if value.get('visible') == 1
        }
        dm.save_codes_json(codes_dict)

    def load_data_async(self, codes_dict):
        """
        Load data in a separate thread to avoid blocking the UI.
        After done, schedule a call to initialize_ui() in the main thread.
        """
        try:
            asyncio.run(self.load_data(codes_dict))
            # Once done, schedule UI init in the Tk main thread
            self.root.after(0, self.initialize_ui)
        except Exception as e:
            logging.error(f"Error loading data: {e}", exc_info=True)

    async def load_data(self, codes_dict):
        # Potential place to do an auto-update check if self.settings["app"]["auto_update"] is True
        # e.g. if self.settings["app"]["auto_update"]: 
        #        do_something()

        self.tags = dm.read_tags()
        await asyncio.sleep(1)

    def initialize_ui(self):
        self.loading_label.destroy()

        # Create a style menu
        self.style_menu = tk.Menu(self.root)
        self.root.config(menu=self.style_menu)
        self.theme_menu = tk.Menu(self.style_menu, tearoff=0)
        self.style_menu.add_cascade(label="Themes", menu=self.theme_menu)
        self.theme_menu.add_command(label='Options', command=self.open_theme_selector)

        # Create the notebook
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)
        self.pages = []

        # Add pages
        self.add_page(HomePage, "Home Page")
        self.add_page(lambda p, n, c: PageOne(p, n, c), "Sauce selection")
        self.add_page(PageTwo, "Favorites")
        self.add_page(PageThree, "Sauce list updater")
        self.add_page(PageFour, "Statistics")

        self.notebook.bind("<<NotebookTabChanged>>", self.adjust_window_size)
        self.adjust_window_size()

    def add_page(self, page_class, title):
        """
        Add a page to the notebook. page_class can be a callable returning a frame instance.
        """
        if callable(page_class):
            page_instance = page_class(self.notebook, self.notebook, self)
        else:
            page_instance = page_class(self.notebook, self.notebook, self)
        self.notebook.add(page_instance, text=title)
        self.pages.append(page_instance)

    def get_page(self, index):
        """Return a reference to a page by its index."""
        return self.pages[index]

    def update_all_pages(self):
        """Call update_page() on all pages if they have it."""
        for page in self.pages:
            if hasattr(page, 'update_page'):
                page.update_page()

    def adjust_window_size(self, event=None):
        """Adjust the window size based on the currently selected page."""
        if not hasattr(self, 'notebook'):
            return 
        current_page = self.notebook.nametowidget(self.notebook.select())
        current_page.update_idletasks()
        width = current_page.winfo_reqwidth()
        height = current_page.winfo_reqheight()
        if width < 500:
            width = 500

        self.root.geometry(f"{width+20}x{height+30}")

    def mainloop(self):
        """Start the Tkinter main loop."""
        self.root.mainloop()

    def open_theme_selector(self):
        """Open the Theme Selector popup."""
        ThemeSelectorPopup(self)


class ThemeSelectorPopup(tk.Toplevel):
    def __init__(self, controller):
        super().__init__(controller.root)
        self.controller = controller
        self.title("Theme Selector")
        self.geometry("300x200")

        self.style = ttk.Style(self.controller.root)
        bg_color = self.style.lookup("TFrame", "background") or "SystemButtonFace"
        self.configure(bg=bg_color)

        label = ttk.Label(self, text="Select a Theme", font=("Arial", 16))
        label.pack(pady=20)

        self.themes = self.controller.root.get_themes()
        self.themes.sort()
        self.selected_theme = ttk.Combobox(self, values=self.themes, state="readonly")
        self.selected_theme.set(self.controller.current_theme)
        self.selected_theme.pack(pady=10)

        apply_button = ttk.Button(self, text="Apply Theme", command=self.apply_theme)
        apply_button.pack(pady=10)

        close_button = ttk.Button(self, text="Close", command=self.destroy)
        close_button.pack(pady=10)

    def apply_theme(self):
        new_theme = self.selected_theme.get()
        self.controller.root.set_theme(new_theme)
        self.controller.current_theme = new_theme
        # Save that choice
        self.controller.settings["theme"]["name"] = new_theme
        dm.write_settings(self.controller.settings)
        # Optionally update the background color
        bg_color = self.style.lookup("TFrame", "background") or "SystemButtonFace"
        self.configure(bg=bg_color)

class HomePage(ttk.Frame):
    """
    The home page showing a welcome label, in-progress comics, ...
    """
    def __init__(self, parent, notebook, controller):
        super().__init__(parent)
        self.notebook = notebook
        self.controller = controller
        self.section_shown = False
        self.in_progress = []

        label = ttk.Label(self, text="Welcome to the sauce selector", font=("Arial", 16))
        label.pack(pady=20)

        self.in_progress_frame = ttk.Frame(self, borderwidth=2, relief="ridge")
        self.section_frame = ttk.Frame(self, borderwidth=2, relief="ridge")
        self.toggle_button_frame = ttk.Frame(self)

        self.section_label = ttk.Label(self.section_frame, text="Which code?")
        self.code_progress_entry = ttk.Entry(self.section_frame, width=8)
        self.section_label.grid(row=0, column=0, padx=10, pady=10)
        self.code_progress_entry.grid(row=0, column=1, padx=10, pady=10)

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

        self.toggle_button = ttk.Button(self.toggle_button_frame, text="Show Section", command=self.toggle_section)
        self.toggle_button.pack(pady=10)

        self.update_page()

    def load_in_progress_data(self):
        in_progress = self.controller.settings['in_progress']
        return in_progress

    def display_in_progress_comics(self):
        self.in_progress_label = ttk.Label(self.in_progress_frame, text='In progress comics')
        self.in_progress_label.grid(row=0, column=1, pady=5)

        for widget in self.in_progress_frame.winfo_children():
            if widget != self.in_progress_label:
                widget.destroy()

        for col in range(6):
            self.in_progress_frame.columnconfigure(col, weight=0, minsize=100)
            
        if self.controller.settings['images']:
            height = 150
            width = 100
        else:
            height = 8
            width = 10

        self.images = [self.load_image(i) for i in self.in_progress]
        for idx, code in enumerate(self.in_progress):
            code = str(code)
            row = (idx // 6) + 1
            col = idx % 6
            button = tk.Button(
                self.in_progress_frame,
                text=str(code),
                image=self.images[idx],
                compound="center",
                font=("Arial", 12),
                width=width,
                height=height,
                command=lambda c=(code, self.in_progress_dict[code]): self.open_in_progress_code(c)
            )
            button.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")

    def create_completion_frame(self, parent):
        frame = ttk.Frame(parent, borderwidth=2, relief="ridge")
        comp_label = ttk.Label(frame, text="What page?")
        self.page_number_entry = ttk.Entry(frame, width=5)
        comp_submit = ttk.Button(frame, text='Submit', command=self.save_progress)

        comp_label.grid(row=0, column=0, pady=10, padx=10)
        self.page_number_entry.grid(row=0, column=1, pady=10, padx=10)
        comp_submit.grid(row=0, column=2, pady=10, padx=10)
        return frame

    def create_like_frame(self, parent):
        frame = ttk.Frame(parent, borderwidth=2, relief="ridge")
        like_button = ttk.Button(frame, text='Favorite', command=self.favorite)
        discard_button = ttk.Button(frame, text='Discard', command=self.discard)
        like_button.grid(row=0, column=1, pady=10, padx=10)
        discard_button.grid(row=0, column=2, pady=10, padx=10)
        return frame

    def toggle_completion_frame(self):
        if self.comp_var.get():
            self.comp_frame.grid(row=1, column=1, pady=10)
            self.like_frame.grid_forget()
        else:
            self.comp_frame.grid_forget()
            self.like_frame.grid(row=1, column=1, pady=10)
        self.controller.adjust_window_size()

    def toggle_section(self):
        if self.section_shown:
            self.section_frame.pack_forget()
            self.toggle_button.config(text="Show Section")
        else:
            self.section_frame.pack(pady=20, padx=20, fill="x")
            self.toggle_button.config(text="Hide Section")
        self.section_shown = not self.section_shown
        self.controller.adjust_window_size()

    def show_section(self):
        if not self.section_shown:
            self.section_frame.pack(pady=20, padx=20, fill="x")
            self.toggle_button.config(text="Hide Section")
            self.section_shown = True
        self.controller.adjust_window_size()

    def favorite(self):
        code_str = self.code_progress_entry.get().strip()
        if not code_str:
            return
        try:
            code = int(code_str)
        except ValueError:
            logging.warning(f"Invalid code: {code_str}")
            return

        name = get_name(code)
        
        fav_dict = {code: {'tags': self.controller.full_list[code]['tags'], 'name':name}}
        
        dm.add_favorites_json(fav_dict)

        if code in self.controller.master_list:
            self.controller.full_list[code]['visible'] = 0

            self.controller.list_update(self.controller.full_list)

            del self.controller.settings['in_progress'][str(code)]
            self._write_in_progress()
            
        if code_str in self.in_progress:
            del self.controller.settings['in_progress'][str(code)]
            self._write_in_progress()

        self._reset_entries()
        self.toggle_section()
        self.controller.update_all_pages()

    def discard(self):
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
            self._write_in_progress()

        self._reset_entries()
        self.toggle_section()
        self.controller.update_all_pages()

    def save_progress(self):
        code = self.code_progress_entry.get().strip()
        page = self.page_number_entry.get().strip()
        
        if int(code) in self.controller.master_list:
            self.controller.full_list[int(code)]['visible'] = 0

            self.controller.list_update(self.controller.full_list)

        self.controller.settings['in_progress'][str(code)] = page
        self._write_in_progress()

        self._reset_entries()
        self.toggle_section()
        self.controller.update_all_pages()

    def load_image(self, code):
        if self.controller.settings['images']:
            image_path = os.path.join(COVERS_DIR, f"{code}.jpg")
            if not os.path.exists(image_path):
                scrape_images(code, COVERS_DIR)
    
            if os.path.exists(image_path):
                try:
                    img = Image.open(image_path).resize((100, 150))
                    return ImageTk.PhotoImage(img)
                except Exception as e:
                    logging.error(f"Error loading image '{image_path}': {e}")
            return None
        else:
            return None

    def open_in_progress_code(self, code_tuple):
        code, page = code_tuple
        url = f'https://nhentai.net/g/{code}/{page}/'
        subprocess.run([r"C:\Program Files\Mozilla Firefox\firefox.exe", "--private-window", url])
        self.show_section()
        self.code_progress_entry.delete(0, tk.END)
        self.code_progress_entry.insert(0, code)

    def update_page(self):
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

    def _write_in_progress(self):
        dm.write_settings(self.controller.settings)

    def _reset_entries(self):
        self.code_progress_entry.delete(0, tk.END)
        self.page_number_entry.delete(0, tk.END)


class PageOne(ttk.Frame):
    """
    Page that displays random codes as clickable images.
    We pick from self.controller.code_keys (the list of code keys).
    """
    def __init__(self, parent, notebook, controller):
        super().__init__(parent)
        self.notebook = notebook
        self.controller = controller
        
        self.button_width = 150
        self.button_height = 225

        self.search_filter = ""

        self.search_frame = ttk.Frame(self)
        self.search_frame.pack(pady=5)

        self.filter_entry = ttk.Entry(self.search_frame, width=20)
        self.filter_entry.pack(side=tk.LEFT, padx=5)
        self.filter_entry.insert(0, "")
        
        self.image_checkbox_frame = ttk.Frame(self)
        self.image_checkbox_frame.pack()
        
        self.image_var = tk.BooleanVar(value=self.controller.settings['images'])
        self.image_checkbox = ttk.Checkbutton(
            self.image_checkbox_frame,
            text="Load images",
            variable=self.image_var,
            command = self.toggle_image_load
        )
        self.image_checkbox.pack()
        

        self.filter_button = ttk.Button(self.search_frame, text="Filter", command=self.apply_filter)
        self.filter_button.pack(side=tk.LEFT, padx=5)

        self.clear_button = ttk.Button(self.search_frame, text="Clear", command=self.clear_filter)
        self.clear_button.pack(side=tk.LEFT, padx=5)

        self.code_buttons_frame = ttk.Frame(self)
        self.code_buttons_frame.pack(pady=10)

        self.refresh_button = ttk.Button(self, text='Refresh', command=self.refresh_codes)
        self.refresh_button.pack(pady=10)

        self.loading_label = ttk.Label(self, text="")
        self.loading_label.pack(pady=5)

        self.update_page()

    def apply_filter(self):
        query = self.filter_entry.get().lower()
        if query:
            filt_tags = [tag for tag in self.controller.tags if query in tag[1].lower()]
            self.search_filter = [t[0] for t in filt_tags]
        else:
            self.search_filter = []
        self.update_page()

    def clear_filter(self):
        self.search_filter = []
        self.filter_entry.delete(0, tk.END)
        self.update_page()
        
    def toggle_image_load(self):
        self.controller.settings['images'] = self.image_var.get()
        dm.write_settings(self.controller.settings)
        self.controller.update_all_pages()

    def refresh_codes(self):
        self.refresh_button.config(state="disabled")
        self.loading_label.config(text="Loading images, please wait...")
        self.update_page()
        self.refresh_button.config(state="normal")
        self.loading_label.config(text="")

    def load_image(self, code):
        if self.controller.settings['images']:
            image_path = os.path.join(COVERS_DIR, f"{code}.jpg")
            if not os.path.exists(image_path):
                scrape_images(code, COVERS_DIR)
            if os.path.exists(image_path):
                try:
                    img = Image.open(image_path).resize((self.button_width, self.button_height))
                    return ImageTk.PhotoImage(img)
                except Exception as e:
                    logging.error(f"Error loading image '{image_path}': {e}")
            return None
        else:
            return None

    def open_code(self, code):
        url = f'https://nhentai.net/g/{code}/'
        subprocess.run([r"C:\Program Files\Mozilla Firefox\firefox.exe", "--private-window", url])
        home_page = self.controller.get_page(0)
        home_page.show_section()
        home_page.code_progress_entry.delete(0, tk.END)
        home_page.code_progress_entry.insert(0, code)

        self.controller.notebook.select(home_page)

    def update_page(self):
        for widget in self.code_buttons_frame.winfo_children():
            widget.destroy()

        # Filter
        if self.search_filter:
            filtered_codes = []
            for c in self.controller.master_list.keys():
                tags_set = self.controller.master_list[c]['tags']
                # if any tag_id in self.search_filter is in tags_set
                if any(t in tags_set for t in self.search_filter):
                    filtered_codes.append(c)
            # filtered_codes = list(filtered_codes.keys())
        else:
            filtered_codes = list(self.controller.master_list.keys())

        if not filtered_codes:
            self.loading_label.config(text="No codes match your filter!")
            return

        selected_codes = random.sample(filtered_codes, min(6, len(filtered_codes)))
        self.images = [self.load_image(c) for c in selected_codes]

        for row in range(2):
            self.code_buttons_frame.rowconfigure(row, weight=0, minsize=self.button_height)
        for col in range(3):
            self.code_buttons_frame.columnconfigure(col, weight=0, minsize=self.button_width)

        for idx, code_val in enumerate(selected_codes):
            row = idx // 3
            col = idx % 3
            button = tk.Button(
                self.code_buttons_frame,
                text=str(code_val),
                image=self.images[idx],
                compound="center",
                font=("Arial", 12),
                width=10,
                height=8,
                command=lambda val=code_val: self.open_code(val)
            )
            # button.config(width = 10, height = 15)
            button.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")

        self.loading_label.config(text="")
        self.controller.adjust_window_size()


class PageTwo(ttk.Frame):
    """Page to display Favorites."""
    def __init__(self, parent, notebook, controller):
        super().__init__(parent)
        self.notebook = notebook
        self.controller = controller

        self.items_per_page = 24
        self.current_page = 0
        
        # -- Search and Sort Frame --
        self.search_sort_frame = ttk.Frame(self)
        self.search_sort_frame.pack(pady=5, fill="x")
        
        # Name search
        ttk.Label(self.search_sort_frame, text="Name:").pack(side=tk.LEFT, padx=5)
        self.name_search_entry = ttk.Entry(self.search_sort_frame, width=20)
        self.name_search_entry.pack(side=tk.LEFT, padx=5)
        self.name_search_entry.bind("<Return>", lambda e: self.apply_filters())

        # Tag filter
        ttk.Label(self.search_sort_frame, text="Tag(s):").pack(side=tk.LEFT, padx=5)
        self.tag_filter_entry = ttk.Entry(self.search_sort_frame, width=15)
        self.tag_filter_entry.pack(side=tk.LEFT, padx=5)
        self.tag_filter_entry.bind("<Return>", lambda e: self.apply_filters())

        # Sort preference
        ttk.Label(self.search_sort_frame, text="Sort:").pack(side=tk.LEFT, padx=5)
        self.sort_combobox = ttk.Combobox(
            self.search_sort_frame,
            values=["Alphabetical", "Random"],
            state="readonly",
            width=12
        )
        self.sort_combobox.pack(side=tk.LEFT, padx=5)
        self.sort_combobox.set("Alphabetical")  # Default sort

        # "Search" button
        self.search_button = ttk.Button(
            self.search_sort_frame,
            text="Search",
            command=self.apply_filters
        )
        self.search_button.pack(side=tk.LEFT, padx=5)
        
        # Items frame
        self.items_frame = ttk.Frame(self)
        self.items_frame.pack(pady=10)

        # Navigation frame
        self.nav_frame = ttk.Frame(self)
        self.nav_frame.pack(pady=10)

        self.prev_button = ttk.Button(self.nav_frame, text="Previous", command=self.prev_page)
        self.prev_button.pack(side=tk.LEFT, padx=10)

        self.next_button = ttk.Button(self.nav_frame, text="Next", command=self.next_page)
        self.next_button.pack(side=tk.LEFT, padx=10)

        self.current_button = None
        self.popup_menu = tk.Menu(self, tearoff=0)
        self.popup_menu.add_command(label="Remove", command=self.discard)
        
        # Store the full favorites list and the filtered version
        self.favorites_dict = {}
        self.displayed_favorites = []

        # Initial loading of data and page
        self.apply_filters()
        
    def apply_filters(self):
        """Load favorites, then filter by name and tag, then sort by user preference."""
        # 1. Load favorites
        self.favorites_dict = dm.load_favorite_json()
        all_favorites = list(self.favorites_dict.keys())

        # 2. Name filter (partial match)
        name_query = self.name_search_entry.get().strip().lower()
        
        # 3. Tag filter (OR logic for multiple comma-separated tag IDs)
        raw_tags = self.tag_filter_entry.get().strip()
        
        tag_ids_to_filter = []
        
        if raw_tags:
            # Split by comma, convert to int if possible
            
            tag_names_to_filter = [tag.strip() for tag in raw_tags.split(",")]
            for tag_input in tag_names_to_filter:
                try:
                    tag_ids_to_filter.append(int(tag_input))
                except ValueError:
                    possible_ids = self.find_tag_id(tag_input)
                    for tag_id in possible_ids:
                        tag_ids_to_filter.append(tag_id)

        # 4. Filter logic
        filtered_codes = []
        for code_val in all_favorites:
            entry = self.favorites_dict[code_val]
            # a) Check name
            match_name = (name_query in entry["name"].lower()) if name_query else True
            # b) Check tags
            if tag_ids_to_filter:
                # We do "OR" matching: any matching tag in the set
                code_tags = set(entry["tags"])
                match_tags = any(tid in code_tags for tid in tag_ids_to_filter)
            else:
                match_tags = True

            if match_name and match_tags:
                filtered_codes.append(code_val)

        # 5. Sort preference
        sort_pref = self.sort_combobox.get()
        if sort_pref == "Alphabetical":
            filtered_codes.sort(
                key=lambda c: self.favorites_dict[c]["name"].lower()
            )
        elif sort_pref == "Random":
            random.shuffle(filtered_codes)

        # Save filtered results
        self.displayed_favorites = filtered_codes
        # Reset pagination and update
        self.current_page = 0
        self.update_page()

    def update_page(self):
        """Display the filtered favorites on the current page."""
        # Clear the frame
        for widget in self.items_frame.winfo_children():
            widget.destroy()

        # Current page slice
        start_index = self.current_page * self.items_per_page
        end_index = start_index + self.items_per_page
        page_items = self.displayed_favorites[start_index:end_index]

        # For image handling
        self.images = [self.load_image(c) for c in page_items]

        # Decide button size based on user settings
        if self.controller.settings['images']:
            height = 150
            width = 100
        else:
            height = 8
            width = 10

        rows, cols = 6, 4
        for idx, code_val in enumerate(page_items):
            r = idx // cols
            c = idx % cols

            # Create a frame for each item
            item_frame = ttk.Frame(self.items_frame)
            item_frame.grid(row=r, column=c, padx=10, pady=0, sticky="nsew")

            # Title / Name above the button
            label_text = self.favorites_dict[code_val]['name']
            label = ttk.Label(
                item_frame, 
                text=label_text,
                wraplength=100,
                justify="center"
            )
            

            # Button (cover image or blank)
            btn_img = self.images[idx]  # images for just this page's items
            button = tk.Button(
                item_frame,
                image=btn_img,
                text=code_val,
                width=width,
                height=height,
                command=lambda val=code_val: self.open_code(val)
            )
            button.pack()
            button.bind("<Button-3>", self.show_popup)
            label.pack(pady=(0, 10))

        # Enable/disable nav buttons
        self.prev_button.config(state=tk.NORMAL if self.current_page > 0 else tk.DISABLED)
        self.next_button.config(
            state=tk.NORMAL if (self.current_page + 1) * self.items_per_page < len(self.displayed_favorites) else tk.DISABLED
        )

        # Adjust the window size if needed
        self.controller.adjust_window_size()

    def next_page(self):
        self.current_page += 1
        self.update_page()

    def prev_page(self):
        self.current_page -= 1
        self.update_page()

    def load_image(self, code):
        if self.controller.settings['images']:
            image_path = os.path.join(COVERS_DIR, f"{code}.jpg")
            if not os.path.exists(image_path):
                scrape_images(code, COVERS_DIR)
            if os.path.exists(image_path):
                try:
                    img = Image.open(image_path).resize((100, 150))
                    return ImageTk.PhotoImage(img)
                except Exception as e:
                    logging.error(f"Error loading image '{image_path}': {e}")
            return None
        else:
            return None

    def open_code(self, code):
        url = f'https://nhentai.net/g/{code}/'
        subprocess.run([r"C:\Program Files\Mozilla Firefox\firefox.exe", "--private-window", url])
        home_page = self.controller.get_page(0)
        self.controller.notebook.select(home_page)

    def show_popup(self, event):
        self.current_button = event.widget
        self.popup_menu.tk_popup(event.x_root, event.y_root)

    def discard(self):
        if self.current_button is None:
            return
        code = int(self.current_button.cget("text"))
        
        fav_dict = dm.load_favorite_json()
        if code in fav_dict:
            del fav_dict[code]
            dm.save_favorites_json(fav_dict)

        # Re-apply the current filters/sort to stay consistent
        self.apply_filters()
        
    def find_tag_id(self, tag_input):
        all_tags = self.controller.tags
        filtered_tags = [tag[0] for tag in all_tags if tag_input in tag[1].lower()]
        return filtered_tags



class PageThree(ttk.Frame):
    """
    Simplified example of async scraping with a progress bar
    """
    def __init__(self, parent, notebook, controller):
        super().__init__(parent)
        self.notebook = notebook
        self.controller = controller

        self.items_per_page = 24
        self.current_page = 0
        
        # Frames
        self.banned_frame = ttk.Frame(self)
        self.banned_labels_frame = ttk.Frame(self.banned_frame)
        self.search_frame = ttk.Frame(self)
        self.items_frame = ttk.Frame(self)
        self.banned_frame.pack(pady=10)
        self.banned_labels_frame.pack(side=tk.TOP, pady=5)
        self.search_frame.pack(pady=10)
        self.items_frame.pack(pady=10)

        # Navigation frame
        self.nav_frame = ttk.Frame(self)
        self.nav_frame.pack(pady=10,fill="x")

        self.prev_button = ttk.Button(self.nav_frame, text="Previous", command=self.prev_page)
        self.prev_button.grid(row=0, column=0, padx=10, pady=10)

        self.next_button = ttk.Button(self.nav_frame, text="Next", command=self.next_page)
        self.next_button.grid(row=0, column=1, padx=10, pady=10)
        
        self.tag_update_button = ttk.Button(self.nav_frame, text="Update tags", command=self.start_tag_fetch)
        self.tag_update_button.grid(row=0, column=5, padx=10, pady=10)

        # Load tags
        self.filtered_tags = self.controller.tags

        # Search bar
        self.search_entry = ttk.Entry(self.search_frame, width=30)
        self.search_entry.pack(side=tk.LEFT, padx=5)
        self.search_entry.bind("<Return>", lambda event: self.search_tags())

        self.search_button = ttk.Button(self.search_frame, text="Search", command=self.search_tags)
        self.search_button.pack(side=tk.LEFT, padx=5)

        # Initialize banned tags
        self.banned_tag_codes = self.controller.settings['banned']['tags']
        self.banned_tag_names = [self.controller.tags[key] for key in self.banned_tag_codes]
        
        # Checkbox to hide banned label
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

        self.scrape_progress = 0
        self.scrape_done = False
        self.scrape_max = 1

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
        
        self.update_page()
        
    def start_tag_fetch(self):
        """Start the async tag fetch process with a loading indicator."""
        self.progress_window = Toplevel(self)
        self.progress_window.title("Fetching Tags")
        self.progress_window.geometry("400x100")

        label = ttk.Label(self.progress_window, text="Fetching tags, please wait...")
        label.pack(pady=10)

        self.progress_bar = Progressbar(self.progress_window, length=300, mode="indeterminate")
        self.progress_bar.pack(pady=5)
        self.progress_bar.start()

        def run_tag_fetch():
            asyncio.run(self.fetch_tags())

        threading.Thread(target=run_tag_fetch, daemon=True).start()

    async def fetch_tags(self):
        try:
            await tag_fetch()
            logging.info("Tag fetching completed.")
        except Exception as e:
            logging.error(f"Error during tag fetching: {e}")
        finally:
            self.progress_bar.stop()
            self.progress_window.destroy()
            
            self.controller.tags = dm.read_tags()
            self.filtered_tags = self.controller.tags
            self.update_page()
        
    def toggle_banned_label(self):
        """Show or hide the banned label based on the checkbox state."""
        if self.hide_banned.get():
            self.banned_label.pack_forget()
            self.banned_title.pack_forget()
        else:
            self.banned_title.pack(side=tk.LEFT, padx=5)
            self.banned_label.pack(side=tk.LEFT, padx=5)

    def code_generate_async(self, update):
        self.progress_window = Toplevel(self)
        self.progress_window.title("Scraping Progress")
        self.progress_window.geometry("400x100")

        label = ttk.Label(self.progress_window, text="Scraping in progress...")
        label.pack(pady=10)

        self.progress_bar = Progressbar(self.progress_window, length=300, mode="determinate")
        self.progress_bar.pack(pady=5)

        def run_in_bg():
            asyncio.run(self._scrape_async(update))

        threading.Thread(target=run_in_bg, daemon=True).start()
        self.check_scrape_progress()
        
    def code_add_async(self, update):
        self.progress_window = Toplevel(self)
        self.progress_window.title("Scraping Progress")
        self.progress_window.geometry("400x100")

        label = ttk.Label(self.progress_window, text="Scraping in progress...")
        label.pack(pady=10)

        self.progress_bar = Progressbar(self.progress_window, length=300, mode="determinate")
        self.progress_bar.pack(pady=5)

        def run_in_bg():
            asyncio.run(self.update_scrape_async(update))

        threading.Thread(target=run_in_bg, daemon=True).start()
        self.check_scrape_progress()

    def check_scrape_progress(self):
        self.progress_bar["maximum"] = self.scrape_max
        self.progress_bar["value"] = self.scrape_progress
        if not self.scrape_done:
            self.after(200, self.check_scrape_progress)
        else:
            self.progress_window.destroy()
            self.controller.codes_and_tags = dm.load_codes_json()
            self.controller.code_keys = list(self.controller.codes_and_tags.keys())
            logging.info("Scraping completed and data reloaded.")
            self.controller.update_all_pages()

    async def _scrape_async(self, update):
        """
        Fully working example of asynchronously scraping
        and updating codes_dict with new codes -> tagIDs.
        """
    
        # 2) Discover last page by reading the first page
        url_base = "https://nhentai.net/search/?q=english"
        for i in self.banned_tag_names:
            url_base = url_base+f'+-{i}'
        url_first = url_base+'&page=1'
            
        try:
            # Because requests is blocking, we run it via asyncio.to_thread
            first_resp = await asyncio.to_thread(requests.get, url_first)
            first_resp.raise_for_status()
        except Exception as e:
            logging.error(f"Error fetching the first page: {e}")
            self.scrape_max = 1
            self.scrape_done = True
            return
    
        soup_first = BeautifulSoup(first_resp.text, "html.parser")
        last_link = soup_first.find("a", class_="last")
        if not last_link:
            logging.warning("Could not find the last-page link. Defaulting to 1.")
            last_page = 1
        else:
            # Extract the page number from something like href="/search/?q=english&page=350"
            try:
                last_page = int(last_link.get("href").split("=")[-1])
            except (ValueError, AttributeError):
                logging.warning("Failed to parse last-page number. Defaulting to 1.")
                last_page = 1
    
        self.scrape_max = last_page
        logging.info(f"Determined last_page={last_page} from the search results.")
    
        # 3) Loop over all pages
        for page_idx in range(1, last_page + 1):
            url = url_base + f"&page={page_idx}"
            try:
                response = await asyncio.to_thread(requests.get, url)
                response.raise_for_status()
            except Exception as e:
                logging.error(f"Error scraping page {page_idx}: {e}")
                # Decide if you want to break or just continue
                continue
    
            soup = BeautifulSoup(response.text, "html.parser")
            comics = soup.find_all("div", class_="gallery")
            if not comics:
                logging.info(f"No galleries found on page {page_idx}. Stopping early.")
                break
    
            for comic in comics:
                # e.g. data-tags="12345 23456 34567"
                tag_strs = comic.get("data-tags", "").split()
                try:
                    tag_ids = set(int(t) for t in tag_strs)
                except ValueError:
                    tag_ids = set()
    
                link_a = comic.find("a")
                if not link_a:
                    continue
                code_link = link_a.get("href", "")
                # Typically /g/123456/
                if code_link.startswith("/g/") and code_link.endswith("/"):
                    try:
                        code_val = int(code_link[3:-1])
                    except ValueError:
                        continue
    
                    # If brand-new code, store it and scrape images
                    if code_val not in self.controller.master_list:
                        self.controller.master_list[code_val] = {'tags':tag_ids, 'visible': 1}
                        # Scrape cover images in a background-friendly manner
                        await asyncio.to_thread(scrape_images, code_val, COVERS_DIR)
    
            # 4) Update progress
            self.scrape_progress = page_idx
            # Let the event loop run other tasks
            await asyncio.sleep(0)
    
        # 5) Save final data
        dm.save_codes_json(self.controller.master_list)
    
        # 6) Mark as done
        self.scrape_done = True
        logging.info("Scraping completed successfully.")
        
    async def update_scrape_async(self, update):
    
        # 2) Discover last page by reading the first page
        url_base = "https://nhentai.net/search/?q=english"
        for i in self.banned_tag_names:
            url_base = url_base+f'+-{i}'
        url_first = url_base+'&page=1'
        
        codes = self.controller.master_list.keys()
            
        try:
            # Because requests is blocking, we run it via asyncio.to_thread
            first_resp = await asyncio.to_thread(requests.get, url_first)
            first_resp.raise_for_status()
        except Exception as e:
            logging.error(f"Error fetching the first page: {e}")
            self.scrape_max = 1
            self.scrape_done = True
            return
        
        soup_first = BeautifulSoup(first_resp.text, "html.parser")
        last_link = soup_first.find("a", class_="last")
        if not last_link:
            logging.warning("Could not find the last-page link. Defaulting to 1.")
            last_page = 1
        else:
            # Extract the page number from something like href="/search/?q=english&page=350"
            try:
                last_page = int(last_link.get("href").split("=")[-1])
            except (ValueError, AttributeError):
                logging.warning("Failed to parse last-page number. Defaulting to 1.")
                last_page = 1
    
        last_code = max(codes)
        if not last_code:
            last_code = 0
    
        self.scrape_max = last_code
        logging.info(f"Determined last_code={last_code} from the saved list.")
    
        # 3) Loop over all pages
        for page_idx in range(1, last_page + 1):
            url = url_base + f"&page={page_idx}"
            try:
                response = await asyncio.to_thread(requests.get, url)
                response.raise_for_status()
            except Exception as e:
                logging.error(f"Error scraping page {page_idx}: {e}")
                # Decide if you want to break or just continue
                continue
    
            soup = BeautifulSoup(response.text, "html.parser")
            comics = soup.find_all("div", class_="gallery")
            if not comics:
                logging.info(f"No galleries found on page {page_idx}. Stopping early.")
                break
    
            for comic in comics:
                # e.g. data-tags="12345 23456 34567"
                tag_strs = comic.get("data-tags", "").split()
                try:
                    tag_ids = set(int(t) for t in tag_strs)
                except ValueError:
                    tag_ids = set()
    
                link_a = comic.find("a")
                if not link_a:
                    continue
                code_link = link_a.get("href", "")
                # Typically /g/123456/
                if code_link.startswith("/g/") and code_link.endswith("/"):
                    try:
                        code_val = int(code_link[3:-1])
                    except ValueError:
                        continue
    
                    # If brand-new code, store it and scrape images
                    if code_val not in self.controller.master_list:
                        self.controller.master_list[code_val] = {'tags':tag_ids, 'visible': 1}
                        # Scrape cover images in a background-friendly manner
                        await asyncio.to_thread(scrape_images, code_val, COVERS_DIR)
            if code_val < last_code:
                break
    
            # 4) Update progress
            self.scrape_progress = code_val - last_code
            # Let the event loop run other tasks
            await asyncio.sleep(0)
    
        # 5) Save final data
        dm.save_codes_json(self.controller.master_list)
    
        # 6) Mark as done
        self.scrape_done = True
        logging.info("Scraping completed successfully.")
            
    def update_page(self):
        """Update the displayed tags on the current page."""
        self.banned_label.config(text=self.banned_tag_names)
        self.banned_label.update_idletasks()  # Ensure wraplength adjusts dynamically
        self.banned_label.config(wraplength=self.winfo_width() - 50)  # Adjust wraplength dynamically

        # Clear items_frame
        for widget in self.items_frame.winfo_children():
            widget.destroy()

        start_index = self.current_page * self.items_per_page
        end_index = start_index + self.items_per_page
        page_items = list(self.filtered_tags.items())[start_index:end_index]

        rows, cols = 6, 4
        for idx, (tag_code, tag_name) in enumerate(page_items):
            r = idx // cols
            c = idx % cols
            button = tk.Button(
                self.items_frame,
                text=str(tag_name),
                compound="center",
                font=("Arial", 12),
                command=lambda code=tag_code, name=tag_name: self.ban_tag((code, name))
            )
            button.grid(row=r, column=c, padx=10, pady=10, sticky="nsew")

        self.prev_button.config(state=tk.NORMAL if self.current_page > 0 else tk.DISABLED)
        self.next_button.config(
            state=tk.NORMAL if (self.current_page + 1)*self.items_per_page < len(self.filtered_tags) else tk.DISABLED
        )
        self.controller.adjust_window_size()

    def next_page(self):
        self.current_page += 1
        self.update_page()

    def prev_page(self):
        self.current_page -= 1
        self.update_page()

    def ban_tag(self, tag):
        """
        Ban or unban a tag. If it's not in banned list, add it. If it is, remove it.
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
        if not self.search_entry.get().strip():
            self._reset_search()
        
        self.update_page()

    def search_tags(self):
        """Filter tags based on the search query."""
        query = self.search_entry.get().lower()
        if query:
            self.filtered_tags = {key: value for key, value in self.controller.tags.items() if query in value.lower()}
        else:
            self.filtered_tags = self.controller.tags
        self.current_page = 0
        self.update_page()
    
    def _reset_search(self):
        """Reset search"""
        self.search_entry.delete(0, tk.END)
        self.filtered_tags = self.controller.tags
        self.update_page()


class PageFour(ttk.Frame):
    """
    Stats page
    """
    def __init__(self, parent, notebook, controller):
        super().__init__(parent)
        self.notebook = notebook
        self.controller = controller

        self.stats_label = ttk.Label(self, text="Statistics", font=("Arial", 16))
        self.stats_label.pack(pady=10)

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

        self.refresh_button = ttk.Button(self, text="Refresh Stats", command=self.update_page)
        self.refresh_button.pack(pady=15)

        self.update_page()

    def update_page(self):
        usable_codes = code_read()  
        self.usable_codes_label.config(text=f"Usable Codes: {len(usable_codes)}")

        in_progress_count = len(list(self.controller.settings['in_progress'].keys()))
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
    os.makedirs(app_settings["paths"]["info_directory"], exist_ok=True)
    os.makedirs(app_settings["paths"]["covers_directory"], exist_ok=True)

    app = MultiPageApp()
    app.mainloop()
