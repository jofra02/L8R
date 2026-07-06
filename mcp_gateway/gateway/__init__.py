"""MCP Gateway — generic OpenAPI/Swagger → MCP tool server.

Loads vendor packs from ``vendors/<name>/`` (manifest + OpenAPI specs +
optional hooks) and exposes every operation as an MCP tool over SSE/stdio.
Fortinet (FortiOS) is the first vendor pack; adding a new appliance means
adding a new pack directory, not new engine code.
"""
