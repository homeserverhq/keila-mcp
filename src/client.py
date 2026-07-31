import os
import datetime as dt
import re
from typing import Any, Optional

import httpx

COMMON_FIELDS: dict[str, set[str]] = {
    "contact": {"id", "email", "first_name", "last_name", "status"},
    "campaign": {"id", "subject", "sender_id", "template_id", "segment_id"},
    "form": {"id", "name", "sender_id", "template_id"},
    "segment": {"id", "name", "filter"},
    "template": {"id", "name", "type"},
    "sender": {"id", "name", "from_email", "from_name"},
    "message": {"id", "recipient_email", "subject"},
    "renderer_output": {"subject", "html_body", "text_body"},
}


def _filter_fields(data: Any, common_set: set[str]) -> Any:
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if k in common_set}
    if isinstance(data, list):
        return [_filter_fields(item, common_set) for item in data]
    return data


def _unwrap(data: Any) -> Any:
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return data


def _normalize_datetime(value: str) -> str:
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$', value):
        return value
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', value):
        raise ValueError(
            f"Invalid datetime: {value}. Timezone offset is required. "
            "Must use format: 2026-06-22T15:00:00-04:00"
        )
    return value


def _denormalize_datetime(value: str) -> str:
    if re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$', value):
        parsed = dt.datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.strftime('%Y-%m-%dT%H:%M:%S+00:00')
    return value


def _denormalize_response(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: _denormalize_response(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_denormalize_response(item) for item in data]
    if isinstance(data, str):
        return _denormalize_datetime(data)
    return data


class KeilaClient:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or os.getenv("KEILA_BASE_URL", "")).rstrip("/")
        if not self.base_url:
            raise ValueError(
                "Keila URL required. Set KEILA_BASE_URL env var "
                "or pass base_url."
            )

    def _get_headers(self, api_key: Optional[str] = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            k: _normalize_datetime(v) if isinstance(v, str) else v
            for k, v in payload.items()
        }

    async def request(
        self,
        method: str,
        path: str,
        api_key: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        url = f"{self.base_url}{path}"
        headers = self._get_headers(api_key)
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.request(method, url, headers=headers, **kwargs)
            if response.status_code >= 400:
                body = response.text[:500]
                raise httpx.HTTPStatusError(
                    f"{response.status_code} {response.reason_phrase} for {method} {path}: {body}",
                    request=response.request, response=response,
                )
            if response.status_code == 204:
                return {}
            if response.headers.get("content-type", "").startswith("application/json"):
                return response.json()
            return {"text": response.text}

    async def get(self, path: str, api_key: Optional[str] = None, **kwargs: Any) -> Any:
        return await self.request("GET", path, api_key, **kwargs)

    async def post(self, path: str, api_key: Optional[str] = None, **kwargs: Any) -> Any:
        return await self.request("POST", path, api_key, **kwargs)

    async def put(self, path: str, api_key: Optional[str] = None, **kwargs: Any) -> Any:
        return await self.request("PUT", path, api_key, **kwargs)

    async def patch(self, path: str, api_key: Optional[str] = None, **kwargs: Any) -> Any:
        return await self.request("PATCH", path, api_key, **kwargs)

    async def delete(self, path: str, api_key: Optional[str] = None, **kwargs: Any) -> Any:
        return await self.request("DELETE", path, api_key, **kwargs)

    # =========================================================================
    # Contacts
    # =========================================================================

    async def list_all_contacts(
        self,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
        page: int = 0,
        page_size: int = 50,
        filter: Optional[str] = None,
    ) -> Any:
        params: dict[str, Any] = {"paginate[page]": str(page), "paginate[page_size]": str(page_size)}
        if filter:
            params["filter"] = filter
        raw = await self.get("/api/v1/contacts", api_key, params=params)
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["contact"])
        return _denormalize_response(data)

    async def get_contact_by_id(
        self,
        contact_id: str,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
        id_type: str = "id",
    ) -> Any:
        raw = await self.get(f"/api/v1/contacts/{contact_id}", api_key, params={"id_type": id_type})
        data = _unwrap(raw)
        if data is None:
            raise Exception("Resource not found")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["contact"])
        return _denormalize_response(data)

    async def create_contact(
        self,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.post("/api/v1/contacts", api_key, json={"data": payload})
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["contact"])
        return _denormalize_response(data)

    async def update_contact(
        self,
        contact_id: str,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
        id_type: str = "id",
    ) -> Any:
        raw = await self.put(f"/api/v1/contacts/{contact_id}", api_key,
                             json={"data": payload}, params={"id_type": id_type})
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["contact"])
        return _denormalize_response(data)

    async def delete_contact_by_id(
        self, contact_id: str, api_key: Optional[str] = None, id_type: str = "id"
    ) -> Any:
        return await self.delete(f"/api/v1/contacts/{contact_id}", api_key, params={"id_type": id_type})

    async def update_contact_data(
        self,
        contact_id: str,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
        id_type: str = "id",
    ) -> Any:
        raw = await self.patch(f"/api/v1/contacts/{contact_id}/data", api_key,
                               json={"data": payload}, params={"id_type": id_type})
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["contact"])
        return _denormalize_response(data)

    async def replace_contact_data(
        self,
        contact_id: str,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
        id_type: str = "id",
    ) -> Any:
        raw = await self.post(f"/api/v1/contacts/{contact_id}/data", api_key,
                              json={"data": payload}, params={"id_type": id_type})
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["contact"])
        return _denormalize_response(data)

    # =========================================================================
    # Campaigns
    # =========================================================================

    async def list_all_campaigns(
        self,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.get("/api/v1/campaigns", api_key)
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["campaign"])
        return _denormalize_response(data)

    async def get_campaign_by_id(
        self,
        campaign_id: str,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.get(f"/api/v1/campaigns/{campaign_id}", api_key)
        data = _unwrap(raw)
        if data is None:
            raise Exception("Resource not found")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["campaign"])
        return _denormalize_response(data)

    async def create_campaign(
        self,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.post("/api/v1/campaigns", api_key, json={"data": payload})
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["campaign"])
        return _denormalize_response(data)

    async def update_campaign(
        self,
        campaign_id: str,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.put(f"/api/v1/campaigns/{campaign_id}", api_key, json={"data": payload})
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["campaign"])
        return _denormalize_response(data)

    async def delete_campaign_by_id(
        self, campaign_id: str, api_key: Optional[str] = None
    ) -> Any:
        return await self.delete(f"/api/v1/campaigns/{campaign_id}", api_key)

    async def send_campaign(
        self,
        campaign_id: str,
        api_key: Optional[str] = None,
    ) -> Any:
        raw = await self.post(f"/api/v1/campaigns/{campaign_id}/actions/send",
                              api_key, json={"data": {}})
        return _unwrap(raw)

    async def schedule_campaign(
        self,
        campaign_id: str,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.post(f"/api/v1/campaigns/{campaign_id}/actions/schedule",
                              api_key, json={"data": self._normalize_payload(payload)})
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["campaign"])
        return _denormalize_response(data)

    # =========================================================================
    # Forms
    # =========================================================================

    async def list_all_forms(
        self,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.get("/api/v1/forms", api_key)
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["form"])
        return _denormalize_response(data)

    async def get_form_by_id(
        self,
        form_id: str,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.get(f"/api/v1/forms/{form_id}", api_key)
        data = _unwrap(raw)
        if data is None:
            raise Exception("Resource not found")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["form"])
        return _denormalize_response(data)

    async def create_form(
        self,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.post("/api/v1/forms", api_key, json={"data": payload})
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["form"])
        return _denormalize_response(data)

    async def update_form(
        self,
        form_id: str,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.put(f"/api/v1/forms/{form_id}", api_key, json={"data": payload})
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["form"])
        return _denormalize_response(data)

    async def delete_form_by_id(
        self, form_id: str, api_key: Optional[str] = None
    ) -> Any:
        return await self.delete(f"/api/v1/forms/{form_id}", api_key)

    async def submit_form(
        self,
        form_id: str,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.post(f"/api/v1/forms/{form_id}/actions/submit",
                              api_key, json={"data": payload})
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["contact"])
        return _denormalize_response(data)

    # =========================================================================
    # Segments
    # =========================================================================

    async def list_all_segments(
        self,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.get("/api/v1/segments", api_key)
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["segment"])
        return _denormalize_response(data)

    async def get_segment_by_id(
        self,
        segment_id: str,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.get(f"/api/v1/segments/{segment_id}", api_key)
        data = _unwrap(raw)
        if data is None:
            raise Exception("Resource not found")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["segment"])
        return _denormalize_response(data)

    async def create_segment(
        self,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.post("/api/v1/segments", api_key, json={"data": payload})
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["segment"])
        return _denormalize_response(data)

    async def update_segment(
        self,
        segment_id: str,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.put(f"/api/v1/segments/{segment_id}", api_key, json={"data": payload})
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["segment"])
        return _denormalize_response(data)

    async def delete_segment_by_id(
        self, segment_id: str, api_key: Optional[str] = None
    ) -> Any:
        return await self.delete(f"/api/v1/segments/{segment_id}", api_key)

    # =========================================================================
    # Templates
    # =========================================================================

    async def list_all_templates(
        self,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.get("/api/v1/templates", api_key)
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["template"])
        return _denormalize_response(data)

    async def get_template_by_id(
        self,
        template_id: str,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.get(f"/api/v1/templates/{template_id}", api_key)
        data = _unwrap(raw)
        if data is None:
            raise Exception("Resource not found")
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["template"])
        return _denormalize_response(data)

    async def create_template(
        self,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.post("/api/v1/templates", api_key, json={"data": payload})
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["template"])
        return _denormalize_response(data)

    async def update_template(
        self,
        template_id: str,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.put(f"/api/v1/templates/{template_id}", api_key, json={"data": payload})
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["template"])
        return _denormalize_response(data)

    async def delete_template_by_id(
        self, template_id: str, api_key: Optional[str] = None
    ) -> Any:
        return await self.delete(f"/api/v1/templates/{template_id}", api_key)

    # =========================================================================
    # Senders
    # =========================================================================

    async def list_all_senders(
        self,
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.get("/api/v1/senders", api_key)
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["sender"])
        return _denormalize_response(data)

    # =========================================================================
    # Transactional Messages
    # =========================================================================

    async def send_transactional_message(
        self,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.post("/api/v1/messages", api_key, json={"data": payload})
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["message"])
        return _denormalize_response(data)

    async def render_transactional_message(
        self,
        payload: dict[str, Any],
        api_key: Optional[str] = None,
        include_all_fields: bool = False,
    ) -> Any:
        raw = await self.post("/api/v1/messages/actions/render", api_key, json={"data": payload})
        data = _unwrap(raw)
        if not include_all_fields:
            data = _filter_fields(data, COMMON_FIELDS["renderer_output"])
        return _denormalize_response(data)

    # =========================================================================
    # System
    # =========================================================================

    async def check_server_status(self, api_key: Optional[str] = None) -> Any:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/v1/openapi")
                return {"status": "connected", "backend_response": response.status_code}
        except Exception as e:
            return {"status": "disconnected", "error": str(e)}
