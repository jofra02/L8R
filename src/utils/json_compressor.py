import json

def compress_json_payload(data, max_list_items=3, max_string_length=150):
    """
    Recursively compress a JSON-like dictionary/list for LLM consumption.
    Truncates long lists, strings, to keep prompt sizes small while retaining schema and sample data.
    """
    if isinstance(data, dict):
        return {k: compress_json_payload(v, max_list_items, max_string_length) for k, v in data.items()}
    elif isinstance(data, list):
        if len(data) > max_list_items:
            # Keep first N items
            compressed = [compress_json_payload(item, max_list_items, max_string_length) for item in data[:max_list_items]]
            compressed.append(f"... and {len(data) - max_list_items} more items []")
            return compressed
        return [compress_json_payload(item, max_list_items, max_string_length) for item in data]
    elif isinstance(data, str):
        if len(data) > max_string_length:
            return data[:max_string_length] + f"... [truncated {len(data) - max_string_length} chars]"
        return data
    else:
        return data
