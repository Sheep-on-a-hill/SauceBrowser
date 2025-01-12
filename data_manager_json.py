import os
import json

INFO_DIR = "Info"  # Will be overridden by settings, if present
COVERS_DIR = "Covers"
USABLE_CODES_JSON = os.path.join(INFO_DIR, "usable_codes.json")
FAVORITE_CODES_JSON = os.path.join(INFO_DIR, "favorite_codes.json")
SETTINGS_JSON = os.path.join(INFO_DIR, "settings.json")
TAGS_JSON = os.path.join(INFO_DIR, "tags.json")

DEFAULT_SETTINGS = {
    "theme": {
        "name": "adapta",
        "font_size": 12,
        "font_family": "Arial"
    },
    "network": {
        "timeout": 30,
        "retry_attempts": 3,
        "proxy": None
    },
    "app": {
        "language": "en-US",
        "auto_update": True,
        "enable_notifications": True,
        "window_size": "400x510"
    },
    "paths": {
        "info_directory": "Info/",
        "covers_directory": "Covers/",
        "log_file": "logs/app.log"
    },
    "banned": {
        "tags": [
            19440,
            32341
        ]
    },
    "in_progress":{
        },
    "images": False
}

def _ensure_settings_file():
    """
    If the settings file doesn't exist, create one with DEFAULT_SETTINGS.
    """
    if not os.path.exists(SETTINGS_JSON):
        os.makedirs(os.path.dirname(SETTINGS_JSON), exist_ok=True)
        write_settings(DEFAULT_SETTINGS)

def load_codes_json():
    """
    Load the JSON file which contains a dict of the form:
      {
        "2": {"tags": [16576, ...], "visible": 1},
        "63": {"tags": [24832, ...], "visible": 1},
        ...
      }
    """
    if not os.path.exists(USABLE_CODES_JSON):
        return {}
    with open(USABLE_CODES_JSON, "r", encoding="utf-8") as f:
        raw_dict = json.load(f)

    final_dict = {}
    for code_str, obj in raw_dict.items():
        code_int = int(code_str)
        tags_list = obj.get("tags", [])
        cover = obj.get("cover", "")
        visible_val = obj.get("visible", 1)
        final_dict[code_int] = {
            "tags": set(tags_list),
            "cover": cover,
            "visible": visible_val
        }
    return final_dict

def save_codes_json(codes_dict):
    """
    Save the dict of codes into JSON, converting sets to lists.
    """
    # Use the settings for info_directory (if you'd like to store in a custom folder)
    settings = load_settings()
    info_dir = settings["paths"]["info_directory"]
    # Adjust your path usage if you decide to place your JSON files in info_dir
    usable_codes_path = os.path.join(info_dir, "usable_codes.json")
    os.makedirs(os.path.dirname(usable_codes_path), exist_ok=True)

    out_dict = {}
    for code_int, data_obj in codes_dict.items():
        tags_set = data_obj.get("tags", set())
        visible_val = data_obj.get("visible", 1)
        cover_url = data_obj.get("cover", "")
        out_dict[str(code_int)] = {
            "tags": list(tags_set),
            "cover": cover_url,
            "visible": visible_val
        }

    with open(usable_codes_path, "w", encoding="utf-8") as f:
        json.dump(out_dict, f, indent=2)

def load_favorite_json():
    """
    Load the JSON file containing favorites. Convert keys to int, tags to sets.
    """
    settings = load_settings()
    info_dir = settings["paths"]["info_directory"]
    favorites_path = os.path.join(info_dir, "favorite_codes.json")
    if not os.path.exists(favorites_path):
        return {}
    try:
        with open(favorites_path, "r", encoding="utf-8") as f:
            raw_dict = json.load(f)
        final_dict = {}
        for code_str, obj in raw_dict.items():
            code_int = int(code_str)
            tags_list = obj.get("tags", [])
            name = obj.get("name", "")
            folder = obj.get("folder", None)
            final_dict[code_int] = {
                "tags": set(tags_list),
                "name": name,
                "folder":folder
            }
        return final_dict   
    except:
        return {}
     
def add_favorites_json(code_dict):
    """
    Merge in a new favorite code. Convert sets to lists before saving.
    """
    out_dict = load_favorite_json()
    out_dict.update(code_dict)

    updated_dict = {}
    for code_int, data_obj in out_dict.items():
        tags_set = data_obj.get("tags", set())
        name_val = data_obj.get("name", "")
        folder = data_obj.get("folder", None)
        updated_dict[str(code_int)] = {
            "tags": list(tags_set),
            "name": name_val,
            "folder": folder
        }
    settings = load_settings()
    info_dir = settings["paths"]["info_directory"]
    favorites_path = os.path.join(info_dir, "favorite_codes.json")
    os.makedirs(os.path.dirname(favorites_path), exist_ok=True)

    with open(favorites_path, "w", encoding="utf-8") as f:
        json.dump(updated_dict, f, indent=2)
        
def save_favorites_json(codes_dict):
    """
    Fully overwrite the favorites file.
    """
    updated_dict = {}
    for code_int, data_obj in codes_dict.items():
        tags_set = data_obj.get("tags", set())
        name_val = data_obj.get("name", "")
        folder = data_obj.get("folder", None)
        updated_dict[str(code_int)] = {
            "tags": list(tags_set),
            "name": name_val,
            "folder":folder
        }
    settings = load_settings()
    info_dir = settings["paths"]["info_directory"]
    favorites_path = os.path.join(info_dir, "favorite_codes.json")
    os.makedirs(os.path.dirname(favorites_path), exist_ok=True)

    with open(favorites_path, "w", encoding="utf-8") as f:
        json.dump(updated_dict, f, indent=2)
        
def load_settings():
    """
    1) Ensure a settings file exists (create if missing).
    2) Load it. Convert banned tags back into tuple form.
    """
    _ensure_settings_file()
    with open(SETTINGS_JSON, "r", encoding="utf-8") as file:
        settings = json.load(file)

    # Convert banned tags from lists back to tuples
    # if "banned" in settings and "tags" in settings["banned"]:
    #     settings["banned"]["tags"] = [tuple(tag) for tag in settings["banned"]["tags"]]
    return settings

def write_settings(settings):
    """
    Write settings dict back to file, making sure banned tags are lists of lists.
    """

    # Ensure the directory exists
    os.makedirs(os.path.dirname(SETTINGS_JSON), exist_ok=True)

    with open(SETTINGS_JSON, "w", encoding="utf-8") as file:
        json.dump(settings, file, indent=2)
        
def read_tags():
    try:
        with open(TAGS_JSON, 'r', encoding='utf-8') as file:
            data = json.load(file)
        tags = {int(key): value for key, value in data.items()}
        return tags
    except FileNotFoundError:
        print(f"Error: The file {TAGS_JSON} was not found.")
    except json.JSONDecodeError as e:
        print(f"Error: Could not decode JSON. {e}")
    except ValueError as e:
        print(f"Error: Could not convert keys to integers. {e}")


def write_tags(data):
    try:
        with open(TAGS_JSON, 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error: Could not write to file. {e}")
