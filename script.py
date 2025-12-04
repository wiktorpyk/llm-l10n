import json
import os
import glob

def combine_locale_files():
    # Define the locales and their order
    locales = ['en', 'cs', 'sk', 'pl']
    
    # Initialize the combined dictionary
    combined_data = {}
    
    # Load all locale files
    locale_data = {}
    for locale in locales:
        filename = f"{locale}.client.json"
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                locale_data[locale] = json.load(f)
        else:
            print(f"Warning: {filename} not found")
            locale_data[locale] = {}
    
    # Use English version as the base for structure and order
    en_data = locale_data['en']
    
    # Build the combined structure following English order
    for category, strings in en_data.items():
        if category not in combined_data:
            combined_data[category] = {}
        
        for key, en_value in strings.items():
            # Initialize with empty strings for all locales
            translations = [""] * len(locales)
            
            # Set English value (first locale)
            translations[0] = en_value
            
            # Set values for other locales if they exist
            for i, locale in enumerate(locales[1:], 1):
                if (category in locale_data[locale] and 
                    key in locale_data[locale][category]):
                    translations[i] = locale_data[locale][category][key]
            
            combined_data[category][key] = translations
    
    return combined_data, locales

def split_and_save_combined_data(combined_data, locales, max_size_bytes=64000):
    """Split combined data into multiple files, each no larger than max_size_bytes"""
    
    # Convert the ordered structure back to JSON to check size
    full_json = json.dumps(combined_data, ensure_ascii=False, indent=2)
    
    if len(full_json.encode('utf-8')) <= max_size_bytes:
        # Single file is small enough
        with open("combined.client.json", 'w', encoding='utf-8') as f:
            f.write(full_json)
        print(f"Combined file created: combined.client.json")
        return ["combined.client.json"]
    
    # Need to split into multiple files
    file_parts = []
    current_part = {}
    current_size = 0
    part_number = 1
    
    # Iterate through categories in the same order as English version
    for category, strings in combined_data.items():
        category_data = {category: strings}
        category_json = json.dumps(category_data, ensure_ascii=False, indent=2)
        category_size = len(category_json.encode('utf-8'))
        
        # If a single category is too large, we need to split it
        if category_size > max_size_bytes:
            # Split this category across multiple files
            category_parts = split_large_category(category, strings, max_size_bytes)
            for i, category_part in enumerate(category_parts):
                filename = f"combined.client.part{part_number}.json"
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(category_part, f, ensure_ascii=False, indent=2)
                file_parts.append(filename)
                print(f"Created: {filename}")
                part_number += 1
        else:
            # Check if adding this category would exceed size limit
            temp_part = current_part.copy()
            temp_part.update(category_data)
            temp_json = json.dumps(temp_part, ensure_ascii=False, indent=2)
            temp_size = len(temp_json.encode('utf-8'))
            
            if temp_size <= max_size_bytes:
                # Add to current part
                current_part = temp_part
                current_size = temp_size
            else:
                # Save current part and start new one
                if current_part:
                    filename = f"combined.client.part{part_number}.json"
                    with open(filename, 'w', encoding='utf-8') as f:
                        json.dump(current_part, f, ensure_ascii=False, indent=2)
                    file_parts.append(filename)
                    print(f"Created: {filename}")
                    part_number += 1
                
                # Start new part with current category
                current_part = category_data
                current_size = category_size
    
    # Don't forget to save the last part
    if current_part:
        filename = f"combined.client.part{part_number}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(current_part, f, ensure_ascii=False, indent=2)
        file_parts.append(filename)
        print(f"Created: {filename}")
    
    return file_parts

def split_large_category(category_name, category_strings, max_size_bytes):
    """Split a single category that's too large into multiple parts"""
    parts = []
    current_part = {}
    current_strings = {}
    
    # Iterate through strings in order
    for key, translations in category_strings.items():
        current_strings[key] = translations
        temp_category = {category_name: current_strings}
        temp_json = json.dumps(temp_category, ensure_ascii=False, indent=2)
        temp_size = len(temp_json.encode('utf-8'))
        
        if temp_size > max_size_bytes:
            # Remove the last key that made it too large and save current part
            if len(current_strings) > 1:
                # Save part without the problematic key
                del current_strings[key]
                parts.append({category_name: current_strings.copy()})
            
            # Start new part with the problematic key
            current_strings = {key: translations}
        else:
            # Continue adding to current part
            current_part = temp_category
    
    # Add the final part
    if current_strings:
        parts.append({category_name: current_strings})
    
    return parts

def print_sample_output(combined_data, max_categories=2, max_strings=3):
    """Print a sample of the combined data structure"""
    print("\nSample of combined structure:")
    print("{")
    
    category_count = 0
    for category, strings in combined_data.items():
        if category_count >= max_categories:
            break
            
        print(f'  "{category}": {{')
        
        string_count = 0
        for key, translations in strings.items():
            if string_count >= max_strings:
                break
                
            print(f'    "{key}": {translations},')
            string_count += 1
        
        print("  },")
        category_count += 1
    
    print("  ...")
    print("}")

if __name__ == "__main__":
    combined_data, locales = combine_locale_files()
    print_sample_output(combined_data)
    
    # Split and save the combined data
    file_parts = split_and_save_combined_data(combined_data, locales)
    
    print(f"\nTotal files created: {len(file_parts)}")
    for filename in file_parts:
        file_size = os.path.getsize(filename)
        print(f"  {filename}: {file_size} bytes")