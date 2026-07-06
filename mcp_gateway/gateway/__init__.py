"""MCP Gateway — generic OpenAPI/Swagger → MCP tool server.

Loads appliance packs from ``vendors/<vendor>/<appliance>/`` (manifest +
OpenAPI specs + optional hooks) and exposes every operation as an MCP tool
over SSE/stdio. FortiGate (``vendors/fortinet/fortigate``) is the first pack;
adding a new appliance means adding a new pack directory, not new engine code.
"""
