import os
import json

INFO_DIR = "Info"
USABLE_CODES_JSON = os.path.join(INFO_DIR, "usable_codes.json")
FAVORITE_CODES_JSON = os.path.join(INFO_DIR, "favorite_codes.json")

def load_codes_json():
    """
    Load the JSON file which contains a dict of the form:
      {
        "2": {"tags": [16576, ...], "visible": 1},
        "63": {"tags": [24832, ...], "visible": 1},
        ...
      }

    We convert the outer keys to int and the tag lists to sets.
    """
    if not os.path.exists(USABLE_CODES_JSON):
        return {}
    with open(USABLE_CODES_JSON, "r", encoding="utf-8") as f:
        raw_dict = json.load(f)

    final_dict = {}
    for code_str, obj in raw_dict.items():
        code_int = int(code_str)
        # Safely extract "tags" list & "visible" key
        tags_list = obj.get("tags", [])
        visible_val = obj.get("visible", 1)
        final_dict[code_int] = {
            "tags": set(tags_list),
            "visible": visible_val
        }
    return final_dict


def save_codes_json(codes_dict):
    """
    Save the dict of:
      {
        2: {"tags": {16576, 17249, ...}, "visible": 1},
        63: {"tags": {...}, "visible": 1},
        ...
      }
    into a JSON file of the form:
      {
        "2": {"tags": [16576, 17249, ...], "visible": 1},
        "63": {"tags": [...], "visible": 1},
        ...
      }

    We convert sets to lists because JSON doesn't support sets.
    """
    os.makedirs(os.path.dirname(USABLE_CODES_JSON), exist_ok=True)

    out_dict = {}
    for code_int, data_obj in codes_dict.items():
        tags_set = data_obj.get("tags", set())
        visible_val = data_obj.get("visible", 1)
        # Convert code to string, tags to list
        out_dict[str(code_int)] = {
            "tags": list(tags_set),
            "visible": visible_val
        }

    with open(USABLE_CODES_JSON, "w", encoding="utf-8") as f:
        json.dump(out_dict, f, indent=2)

def load_favorite_json():
    """
    Load the JSON file which contains a dict of the form:
      {
        "2": {"tags": [16576, ...], "name": {name}},
        "63": {"tags": [24832, ...], "name": {name}},
        ...
      }

    We convert the outer keys to int and the tag lists to sets.
    """
    if not os.path.exists(FAVORITE_CODES_JSON):
        return {}
    try:
        with open(FAVORITE_CODES_JSON, "r", encoding="utf-8") as f:
            raw_dict = json.load(f)
    
        final_dict = {}
        for code_str, obj in raw_dict.items():
            code_int = int(code_str)
            # Safely extract "tags" list & "visible" key
            tags_list = obj.get("tags", [])
            name = obj.get("name", "")
            final_dict[code_int] = {
                "tags": set(tags_list),
                "name": name
            }
        return final_dict   
    except:
        return {}
     

def add_favorites_json(code_dict):
    """

    We convert sets to lists because JSON doesn't support sets.
    """
    os.makedirs(os.path.dirname(FAVORITE_CODES_JSON), exist_ok=True)

    # Load existing data
    out_dict = load_favorite_json()
    out_dict.update(code_dict)

    # Create a new dictionary to store the transformed data
    updated_dict = {}

    # Iterate over the original dictionary without modifying it
    for code_int, data_obj in out_dict.items():
        tags_set = data_obj.get("tags", set())
        visible_val = data_obj.get("name", "")
        # Add transformed data to the new dictionary
        updated_dict[str(code_int)] = {
            "tags": list(tags_set),
            "name": visible_val
        }

    # Save the updated dictionary
    with open(FAVORITE_CODES_JSON, "w", encoding="utf-8") as f:
        json.dump(updated_dict, f, indent=2)
        
def save_favorites_json(codes_dict):
    os.makedirs(os.path.dirname(FAVORITE_CODES_JSON), exist_ok=True)

    out_dict = {}
    for code_int, data_obj in codes_dict.items():
        tags_set = data_obj.get("tags", set())
        name = data_obj.get("name", "")
        # Convert code to string, tags to list
        out_dict[str(code_int)] = {
            "tags": list(tags_set),
            "name": name
        }

    with open(FAVORITE_CODES_JSON, "w", encoding="utf-8") as f:
        json.dump(out_dict, f, indent=2)
        