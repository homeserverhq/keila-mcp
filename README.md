# Keila MCP Multitenant Proxy Server

This repository contains a Model Context Protocol (MCP) server that acts as a secure, multi-tenant proxy between an AI Assistant and the Keila backend API. It exposes **34 MCP tools** covering 7 resource domains with full CRUD, transactional messaging, and system operations.

## ✨ Features

- **🔑 Identity Passthrough** — Extracts the `Authorization: Bearer <token>` header from incoming HTTP requests and forwards it to the Keila API without server-side authentication.
- **👥 Multi-Tenancy** — Uses Python `contextvars` to maintain thread-safe user identity isolation.
- **📊 Full Keila Coverage** — 34 tools mapped to Keila API endpoints across 7 resource domains.
- **⚡ TOON Optimization** — Bulk list responses are automatically compressed using TOON.
- **⚡ Efficient Gets** — GET responses return only commonly used fields by default. Full objects are available via an `include_all_fields` flag.
- **🏷️ Tool Tags** — Every tool is tagged by operation type (read/write), access level (basic/primary/advanced), and project namespace.
- **🧪 Comprehensive Testing** — Automated tests covering all 34 tool domains.

## 🔧 Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `KEILA_BASE_URL` | Yes | Docker-internal URL of the Keila API (e.g. `http://keila-app:4000`) |
| `MCP_SERVER_PORT` | Yes | Port number the MCP server listens on |
| `ALLOW_ALL_AGGREGATE` | No | When `true`, aggregate listing tools honor the `include_all_fields` parameter. When `false` (default), the parameter is silently forced to `False` for aggregate list operations. |
| `IS_STATEFUL` | No | When `true`, uses stateful Streamable HTTP with session tracking. When `false` (default), uses stateless mode. |

## 📦 Installation & Local Development

1. Ensure you have Python 3.12+ installed.
2. Install dependencies:
   ```bash
   pip install fastmcp httpx pydantic uvicorn toon-mcp-server
   ```
3. Run the server:
   ```bash
   export KEILA_BASE_URL=http://localhost:7823
   export MCP_SERVER_PORT=5721
   python -m src.main
   ```

## 🐳 Docker Deployment

Build and run the server using Docker:

```bash
docker build -t keila-mcp .
docker run -d --name keila-mcp --network dock-ext \
    -p 5721:5721 \
    -e KEILA_BASE_URL="http://keila-app:4000" \
    -e MCP_SERVER_PORT=5721 \
    -e API_KEY="<your-api-key>" \
    keila-mcp
```

The MCP server serves at `http://keila-mcp:5721/mcp` (Streamable HTTP).

## ⚠️ Important Notes

- **📋 `include_all_fields`** — The `include_all_fields` parameter (available on all `get_*` and `list_*` tools) controls whether all available fields are included in responses (Default False for performance, set True for all fields).
- **⚡ TOON Compression** — All bulk list responses are automatically compressed using TOON.
- **📝 Required Fields & Defaults** — Each `create_*` tool requires specific key fields. All other fields default to empty strings or reasonable values.

## 🛠️ API Tool Mapping

The server implements 34 MCP tools organized into the following categories:

### 📡 Contacts (7 tools)
- `list_all_contacts` — List all contact records
- `get_contact_by_id` — Get a single contact by ID, email, or external ID
- `create_contact` — Create a new contact
- `update_contact` — Update an existing contact
- `delete_contact_by_id` — Delete a contact by ID, email, or external ID
- `update_contact_data` — Shallow-merge custom data fields on a contact
- `replace_contact_data` — Replace all custom data fields on a contact

### 📡 Campaigns (7 tools)
- `list_all_campaigns` — List all campaign records
- `get_campaign_by_id` — Get a single campaign by ID
- `create_campaign` — Create a new campaign
- `update_campaign` — Update an existing campaign
- `delete_campaign_by_id` — Delete a campaign by ID
- `send_campaign` — Queue a campaign for immediate delivery
- `schedule_campaign` — Schedule a campaign for future delivery

### 📡 Forms (6 tools)
- `list_all_forms` — List all form records
- `get_form_by_id` — Get a single form by ID
- `create_form` — Create a new form
- `update_form` — Update an existing form
- `delete_form_by_id` — Delete a form by ID
- `submit_form` — Submit a form to create or update a contact

### 📡 Segments (5 tools)
- `list_all_segments` — List all segment records
- `get_segment_by_id` — Get a single segment by ID
- `create_segment` — Create a new segment
- `update_segment` — Update an existing segment
- `delete_segment_by_id` — Delete a segment by ID

### 📡 Templates (5 tools)
- `list_all_templates` — List all template records
- `get_template_by_id` — Get a single template by ID
- `create_template` — Create a new template
- `update_template` — Update an existing template
- `delete_template_by_id` — Delete a template by ID

### 📡 Senders (1 tool)
- `list_all_senders` — List all sender records

### 📡 Transactional Messages (2 tools)
- `send_transactional_message` — Send a transactional message
- `render_transactional_message` — Render a transactional message without sending

### 🛠️ System Tools (1 tool)
- `check_server_status` — Check connectivity to the Keila backend
