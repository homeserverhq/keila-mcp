import json
import os
import sys
from contextvars import ContextVar
from typing import Any, Optional

from fastmcp import FastMCP, Context
from pydantic import BaseModel, ConfigDict, Field, model_validator
from toon_mcp import json_to_toon

from .client import KeilaClient

_current_user_token: ContextVar[Optional[str]] = ContextVar("current_user_token", default=None)


class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode()
            if auth_header.startswith("Bearer "):
                _current_user_token.set(auth_header[7:])
        await self.app(scope, receive, send)


mcp = FastMCP("Keila-mcp-server")

_client: Optional[KeilaClient] = None


def get_client() -> KeilaClient:
    global _client
    if _client is None:
        _client = KeilaClient()
    return _client


def get_user_token() -> Optional[str]:
    return _current_user_token.get()


ALLOW_ALL_AGGREGATE = os.getenv("ALLOW_ALL_AGGREGATE", "false").lower() in ("true", "1", "yes")
IS_STATEFUL = os.getenv("IS_STATEFUL", "false").lower() in ("true", "1", "yes")

# =============================================================================
# Pydantic Typed Models (replaces all JSON-string params)
# =============================================================================


class ContactData(BaseModel):
    model_config = ConfigDict(extra="allow")


class CampaignData(BaseModel):
    model_config = ConfigDict(extra="allow")


class TemplateAssigns(BaseModel):
    model_config = ConfigDict(extra="allow")


class MessageAssigns(BaseModel):
    model_config = ConfigDict(extra="allow")


class SegmentFilter(BaseModel):
    model_config = ConfigDict(extra="allow")


class BlockData(BaseModel):
    model_config = ConfigDict(extra="allow")


class ContentBlock(BaseModel):
    id: Optional[str] = None
    type: str
    data: BlockData = Field(default_factory=BlockData)


class CampaignJsonBody(BaseModel):
    blocks: list[ContentBlock] = []


class ContentSlots(BaseModel):
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def _validate_values(self):
        for k, v in (self.__pydantic_extra__ or {}).items():
            if not isinstance(v, str):
                raise ValueError(f"Content slot '{k}' value must be a string, got {type(v).__name__}")
        return self


class FormFieldAllowedValue(BaseModel):
    label: str
    value: str


class FormField(BaseModel):
    field: str
    required: Optional[bool] = None
    cast: Optional[bool] = None
    key: Optional[str] = None
    type: Optional[str] = None
    label: Optional[str] = None
    placeholder: Optional[str] = None
    description: Optional[str] = None
    allowed_values: Optional[list[FormFieldAllowedValue]] = None


class FormSettings(BaseModel):
    captcha_required: Optional[bool] = None
    double_opt_in_required: Optional[bool] = None
    double_opt_in_subject: Optional[str] = None
    double_opt_in_markdown_body: Optional[str] = None
    double_opt_in_message: Optional[str] = None
    double_opt_in_url: Optional[str] = None
    csrf_disabled: Optional[bool] = None
    intro_text: Optional[str] = None
    fine_print: Optional[str] = None
    body_bg_color: Optional[str] = None
    form_bg_color: Optional[str] = None
    text_color: Optional[str] = None
    submit_label: Optional[str] = None
    submit_bg_color: Optional[str] = None
    submit_text_color: Optional[str] = None
    input_bg_color: Optional[str] = None
    input_border_color: Optional[str] = None
    input_text_color: Optional[str] = None
    success_text: Optional[str] = None
    success_url: Optional[str] = None
    failure_text: Optional[str] = None
    failure_url: Optional[str] = None
    model_config = ConfigDict(extra="allow")


# =============================================================================
# Pydantic Contract Models
# =============================================================================


class CreateContactParam(BaseModel):
    email: str
    first_name: str = ""
    last_name: str = ""
    external_id: str = ""
    status: str = "active"
    data: Optional[ContactData] = None


class UpdateContactParam(BaseModel):
    id: str
    id_type: str = "id"
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    external_id: Optional[str] = None
    status: Optional[str] = None
    data: Optional[ContactData] = None


class UpdateContactDataParam(BaseModel):
    id: str
    data: ContactData
    id_type: str = "id"


class ReplaceContactDataParam(BaseModel):
    id: str
    data: ContactData
    id_type: str = "id"


class CreateCampaignParam(BaseModel):
    subject: str
    settings_type: str
    text_body: str = ""
    json_body: Optional[CampaignJsonBody] = None
    mjml_body: str = ""
    html_body: str = ""
    mjml_content: Optional[ContentSlots] = None
    html_content: Optional[ContentSlots] = None
    text_content: Optional[ContentSlots] = None
    data: Optional[CampaignData] = None
    template_id: str = ""
    sender_id: str = ""
    segment_id: str = ""
    preview_text: str = ""


class UpdateCampaignParam(BaseModel):
    id: str
    subject: Optional[str] = None
    text_body: Optional[str] = None
    json_body: Optional[CampaignJsonBody] = None
    mjml_body: Optional[str] = None
    html_body: Optional[str] = None
    mjml_content: Optional[ContentSlots] = None
    html_content: Optional[ContentSlots] = None
    text_content: Optional[ContentSlots] = None
    data: Optional[CampaignData] = None
    settings_type: Optional[str] = None
    template_id: Optional[str] = None
    sender_id: Optional[str] = None
    segment_id: Optional[str] = None
    preview_text: Optional[str] = None


class CreateFormParam(BaseModel):
    name: str
    sender_id: str = ""
    template_id: str = ""
    settings: Optional[FormSettings] = None
    fields: Optional[list[FormField]] = None


class UpdateFormParam(BaseModel):
    id: str
    name: Optional[str] = None
    sender_id: Optional[str] = None
    template_id: Optional[str] = None
    settings: Optional[FormSettings] = None
    fields: Optional[list[FormField]] = None


class SubmitFormParam(BaseModel):
    id: str
    email: str
    first_name: str = ""
    last_name: str = ""
    external_id: str = ""
    status: str = "active"
    data: Optional[ContactData] = None


class CreateSegmentParam(BaseModel):
    name: str
    filter: SegmentFilter


class UpdateSegmentParam(BaseModel):
    id: str
    name: Optional[str] = None
    filter: Optional[SegmentFilter] = None


class CreateTemplateParam(BaseModel):
    name: str
    type: str
    mjml_body: str = ""
    html_body: str = ""
    text_body: str = ""
    styles: str = ""
    assigns: Optional[TemplateAssigns] = None


class UpdateTemplateParam(BaseModel):
    id: str
    name: Optional[str] = None
    type: Optional[str] = None
    mjml_body: Optional[str] = None
    html_body: Optional[str] = None
    text_body: Optional[str] = None
    styles: Optional[str] = None
    assigns: Optional[TemplateAssigns] = None


class TransactionalMessageParam(BaseModel):
    type: str
    sender_id: str
    recipient_email: str = ""
    recipient_name: str = ""
    cc: list[str] = []
    bcc: list[str] = []
    contact_id: str = ""
    external_contact_id: str = ""
    subject: str = ""
    text_body: str = ""
    html_body: str = ""
    mjml_body: str = ""
    mjml_content: Optional[ContentSlots] = None
    html_content: Optional[ContentSlots] = None
    text_content: Optional[ContentSlots] = None
    assigns: Optional[MessageAssigns] = None
    template_id: str = ""


# =============================================================================
# System Tools
# =============================================================================


@mcp.tool(tags={"read", "basic", "keila"})
async def check_server_status(ctx: Context = None) -> dict[str, Any]:
    """Check connectivity to the Keila backend."""
    return await get_client().check_server_status(get_user_token())


# =============================================================================
# Contacts Tools
# =============================================================================


@mcp.tool(tags={"read", "basic", "keila"})
async def list_all_contacts(
    include_all_fields: bool = False,
    page: int = 0,
    page_size: int = 50,
    filter: Optional[SegmentFilter] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """List all contact records.

    Args:
        include_all_fields: Default False (common fields only). Set True for all fields.
        page: Page number for pagination. Defaults to 0.
        page_size: Number of records per page. Defaults to 50.
        filter: Filter criteria object.
    """
    data = await get_client().list_all_contacts(
        get_user_token(),
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False,
        page=page,
        page_size=page_size,
        filter=json.dumps(filter.model_dump()) if filter else None,
    )
    return {"items": json_to_toon(data)}


@mcp.tool(tags={"read", "basic", "keila"})
async def get_contact_by_id(
    id: str,
    id_type: str = "id",
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Get a single contact by its ID, email, or external ID.

    Args:
        id: The unique ID, email, or external ID of the contact.
        id_type: id, email, or external_id. Defaults to id.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    return await get_client().get_contact_by_id(
        id, get_user_token(), include_all_fields=include_all_fields, id_type=id_type
    )


@mcp.tool(tags={"write", "primary", "keila"})
async def create_contact(
    email: str,
    first_name: str = "",
    last_name: str = "",
    external_id: str = "",
    status: str = "active",
    data: Optional[ContactData] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Create a new contact.

    Args:
        email: Email address of the new contact.
        first_name: First name of the contact.
        last_name: Last name of the contact.
        external_id: External ID for cross-referencing.
        status: active, unsubscribed, or unreachable. Defaults to active.
        data: Custom data fields (key-value object).
    """
    params = CreateContactParam(
        email=email, first_name=first_name, last_name=last_name,
        external_id=external_id, status=status, data=data,
    )
    p = params.model_dump(exclude_unset=True, exclude_none=True)
    return await get_client().create_contact(
        p, get_user_token(), include_all_fields=ALLOW_ALL_AGGREGATE
    )


@mcp.tool(tags={"write", "primary", "keila"})
async def update_contact(
    id: str,
    id_type: str = "id",
    email: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    external_id: Optional[str] = None,
    status: Optional[str] = None,
    data: Optional[ContactData] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Update an existing contact.

    Args:
        id: The unique ID, email, or external ID of the contact.
        id_type: id, email, or external_id. Defaults to id.
        email: Updated email address.
        first_name: Updated first name.
        last_name: Updated last name.
        external_id: Updated external ID.
        status: active, unsubscribed, or unreachable.
        data: Custom data fields (key-value object).
    """
    params = UpdateContactParam(
        id=id, id_type=id_type, email=email, first_name=first_name,
        last_name=last_name, external_id=external_id, status=status, data=data,
    )
    p = params.model_dump(exclude_unset=True, exclude_none=True)
    for key in ("id", "id_type"):
        p.pop(key, None)
    return await get_client().update_contact(
        id, p, get_user_token(), include_all_fields=ALLOW_ALL_AGGREGATE, id_type=id_type
    )


@mcp.tool(tags={"write", "basic", "keila"})
async def delete_contact_by_id(
    id: str,
    id_type: str = "id",
    ctx: Context = None,
) -> dict[str, Any]:
    """Delete a contact by its ID, email, or external ID.

    Args:
        id: The unique ID, email, or external ID of the contact to delete.
        id_type: id, email, or external_id. Defaults to id.
    """
    await get_client().delete_contact_by_id(id, get_user_token(), id_type=id_type)
    return {"deleted": True, "id": id}


@mcp.tool(tags={"write", "primary", "keila"})
async def update_contact_data(
    id: str,
    data: ContactData,
    id_type: str = "id",
    ctx: Context = None,
) -> dict[str, Any]:
    """Shallow-merge custom data fields on a contact.

    Args:
        id: The unique ID, email, or external ID of the contact.
        data: Custom data fields (key-value object).
        id_type: id, email, or external_id. Defaults to id.
    """
    params = UpdateContactDataParam(id=id, data=data, id_type=id_type)
    p = params.model_dump(exclude_unset=True, exclude_none=True)
    return await get_client().update_contact_data(
        id, p["data"], get_user_token(),
        include_all_fields=ALLOW_ALL_AGGREGATE, id_type=id_type,
    )


@mcp.tool(tags={"write", "primary", "keila"})
async def replace_contact_data(
    id: str,
    data: ContactData,
    id_type: str = "id",
    ctx: Context = None,
) -> dict[str, Any]:
    """Replace all custom data fields on a contact.

    Args:
        id: The unique ID, email, or external ID of the contact.
        data: Custom data fields (key-value object).
        id_type: id, email, or external_id. Defaults to id.
    """
    params = ReplaceContactDataParam(id=id, data=data, id_type=id_type)
    p = params.model_dump(exclude_unset=True, exclude_none=True)
    return await get_client().replace_contact_data(
        id, p["data"], get_user_token(),
        include_all_fields=ALLOW_ALL_AGGREGATE, id_type=id_type,
    )


# =============================================================================
# Campaigns Tools
# =============================================================================


@mcp.tool(tags={"read", "basic", "keila"})
async def list_all_campaigns(
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """List all campaign records.

    Args:
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    data = await get_client().list_all_campaigns(
        get_user_token(),
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False,
    )
    return {"items": json_to_toon(data)}


@mcp.tool(tags={"read", "basic", "keila"})
async def get_campaign_by_id(
    id: str,
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Get a single campaign by its ID.

    Args:
        id: The unique ID of the campaign.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    return await get_client().get_campaign_by_id(
        id, get_user_token(), include_all_fields=include_all_fields
    )


@mcp.tool(tags={"write", "primary", "keila"})
async def create_campaign(
    subject: str,
    settings_type: str,
    text_body: str = "",
    json_body: Optional[CampaignJsonBody] = None,
    mjml_body: str = "",
    html_body: str = "",
    mjml_content: Optional[ContentSlots] = None,
    html_content: Optional[ContentSlots] = None,
    text_content: Optional[ContentSlots] = None,
    data: Optional[CampaignData] = None,
    template_id: str = "",
    sender_id: str = "",
    segment_id: str = "",
    preview_text: str = "",
    ctx: Context = None,
) -> dict[str, Any]:
    """Create a new campaign.

    Args:
        subject: Subject line of the campaign.
        settings_type: Content type: text, markdown, block, mjml, or html.
        text_body: Plain text body content.
        json_body: Structured block content object.
        mjml_body: MJML markup body.
        html_body: HTML body content.
        mjml_content: Map of named MJML content slots.
        html_content: Map of named HTML content slots.
        text_content: Map of named text content slots.
        data: Custom data fields (key-value object).
        template_id: ID of the template to use.
        sender_id: ID of the sender.
        segment_id: ID of the target segment.
        preview_text: Preview text shown after the subject line.
    """
    params = CreateCampaignParam(
        subject=subject, settings_type=settings_type,
        text_body=text_body, json_body=json_body,
        mjml_body=mjml_body, html_body=html_body,
        mjml_content=mjml_content, html_content=html_content,
        text_content=text_content, data=data,
        template_id=template_id, sender_id=sender_id,
        segment_id=segment_id, preview_text=preview_text,
    )
    p = params.model_dump(exclude_unset=True, exclude_none=True)
    p["settings"] = {"type": p.pop("settings_type")}
    for key in ("template_id", "sender_id", "segment_id"):
        if key in p and not p[key]:
            del p[key]
    return await get_client().create_campaign(
        p, get_user_token(), include_all_fields=ALLOW_ALL_AGGREGATE
    )


@mcp.tool(tags={"write", "primary", "keila"})
async def update_campaign(
    id: str,
    subject: Optional[str] = None,
    text_body: Optional[str] = None,
    json_body: Optional[CampaignJsonBody] = None,
    mjml_body: Optional[str] = None,
    html_body: Optional[str] = None,
    mjml_content: Optional[ContentSlots] = None,
    html_content: Optional[ContentSlots] = None,
    text_content: Optional[ContentSlots] = None,
    data: Optional[CampaignData] = None,
    settings_type: Optional[str] = None,
    template_id: Optional[str] = None,
    sender_id: Optional[str] = None,
    segment_id: Optional[str] = None,
    preview_text: Optional[str] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Update an existing campaign.

    Args:
        id: The unique ID of the campaign to update.
        subject: Updated subject line.
        text_body: Updated plain text body.
        json_body: Structured block content object.
        mjml_body: Updated MJML markup body.
        html_body: Updated HTML body.
        mjml_content: Map of named MJML content slots.
        html_content: Map of named HTML content slots.
        text_content: Map of named text content slots.
        data: Custom data fields (key-value object).
        settings_type: text, markdown, block, mjml, or html.
        template_id: Updated template ID.
        sender_id: Updated sender ID.
        segment_id: Updated segment ID.
        preview_text: Updated preview text.
    """
    params = UpdateCampaignParam(
        id=id, subject=subject, text_body=text_body,
        json_body=json_body, mjml_body=mjml_body,
        html_body=html_body, mjml_content=mjml_content,
        html_content=html_content, text_content=text_content,
        data=data, settings_type=settings_type,
        template_id=template_id, sender_id=sender_id,
        segment_id=segment_id, preview_text=preview_text,
    )
    p = params.model_dump(exclude_unset=True, exclude_none=True)
    p.pop("id", None)
    if "settings_type" in p:
        p["settings"] = {"type": p.pop("settings_type")}
    for key in ("template_id", "sender_id", "segment_id"):
        if key in p and not p[key]:
            del p[key]
    return await get_client().update_campaign(
        id, p, get_user_token(), include_all_fields=ALLOW_ALL_AGGREGATE
    )


@mcp.tool(tags={"write", "basic", "keila"})
async def delete_campaign_by_id(
    id: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """Delete a campaign by its ID.

    Args:
        id: The unique ID of the campaign to delete.
    """
    await get_client().delete_campaign_by_id(id, get_user_token())
    return {"deleted": True, "id": id}


@mcp.tool(tags={"write", "primary", "keila"})
async def send_campaign(
    id: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """Queue a campaign for immediate delivery.

    Args:
        id: The unique ID of the campaign to send.
    """
    result = await get_client().send_campaign(id, get_user_token())
    return {"delivery_queued": result.get("delivery_queued", True), "campaign_id": id}


@mcp.tool(tags={"write", "primary", "keila"})
async def schedule_campaign(
    id: str,
    scheduled_for: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """Schedule a campaign for future delivery.

    Args:
        id: The unique ID of the campaign to schedule.
        scheduled_for: ISO 8601 format (2026-06-22T15:00:00-04:00).
    """
    return await get_client().schedule_campaign(
        id, {"scheduled_for": scheduled_for}, get_user_token(),
        include_all_fields=ALLOW_ALL_AGGREGATE,
    )


# =============================================================================
# Forms Tools
# =============================================================================


@mcp.tool(tags={"read", "basic", "keila"})
async def list_all_forms(
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """List all form records.

    Args:
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    data = await get_client().list_all_forms(
        get_user_token(),
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False,
    )
    return {"items": json_to_toon(data)}


@mcp.tool(tags={"read", "basic", "keila"})
async def get_form_by_id(
    id: str,
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Get a single form by its ID.

    Args:
        id: The unique ID of the form.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    return await get_client().get_form_by_id(
        id, get_user_token(), include_all_fields=include_all_fields
    )


@mcp.tool(tags={"write", "primary", "keila"})
async def create_form(
    name: str,
    sender_id: str = "",
    template_id: str = "",
    settings: Optional[FormSettings] = None,
    fields: Optional[list[FormField]] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Create a new form.

    Args:
        name: Name of the new form.
        sender_id: ID of the sender for confirmation emails.
        template_id: ID of the template for confirmation emails.
        settings: Form settings object.
        fields: Array of form field configurations.
    """
    params = CreateFormParam(
        name=name, sender_id=sender_id, template_id=template_id,
        settings=settings, fields=fields,
    )
    p = params.model_dump(exclude_unset=True, exclude_none=True)
    if "sender_id" in p and not p.get("sender_id"):
        del p["sender_id"]
    if "template_id" in p and not p.get("template_id"):
        del p["template_id"]
    return await get_client().create_form(
        p, get_user_token(), include_all_fields=ALLOW_ALL_AGGREGATE
    )


@mcp.tool(tags={"write", "primary", "keila"})
async def update_form(
    id: str,
    name: Optional[str] = None,
    sender_id: Optional[str] = None,
    template_id: Optional[str] = None,
    settings: Optional[FormSettings] = None,
    fields: Optional[list[FormField]] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Update an existing form.

    Args:
        id: The unique ID of the form to update.
        name: Updated name of the form.
        sender_id: Updated sender ID.
        template_id: Updated template ID.
        settings: Form settings object.
        fields: Array of form field configurations.
    """
    params = UpdateFormParam(
        id=id, name=name, sender_id=sender_id, template_id=template_id,
        settings=settings, fields=fields,
    )
    p = params.model_dump(exclude_unset=True, exclude_none=True)
    p.pop("id", None)
    if "sender_id" in p and not p.get("sender_id"):
        del p["sender_id"]
    if "template_id" in p and not p.get("template_id"):
        del p["template_id"]
    return await get_client().update_form(
        id, p, get_user_token(), include_all_fields=ALLOW_ALL_AGGREGATE
    )


@mcp.tool(tags={"write", "basic", "keila"})
async def delete_form_by_id(
    id: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """Delete a form by its ID.

    Args:
        id: The unique ID of the form to delete.
    """
    await get_client().delete_form_by_id(id, get_user_token())
    return {"deleted": True, "id": id}


@mcp.tool(tags={"write", "primary", "keila"})
async def submit_form(
    id: str,
    email: str,
    first_name: str = "",
    last_name: str = "",
    external_id: str = "",
    status: str = "active",
    data: Optional[ContactData] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Submit a form to create or update a contact.

    Args:
        id: The unique ID of the form to submit.
        email: Email address of the contact.
        first_name: First name of the contact.
        last_name: Last name of the contact.
        external_id: External ID for cross-referencing.
        status: active, unsubscribed, or unreachable. Defaults to active.
        data: Custom data fields (key-value object).
    """
    params = SubmitFormParam(
        id=id, email=email, first_name=first_name, last_name=last_name,
        external_id=external_id, status=status, data=data,
    )
    p = params.model_dump(exclude_unset=True, exclude_none=True)
    p.pop("id", None)
    return await get_client().submit_form(
        id, p, get_user_token(), include_all_fields=ALLOW_ALL_AGGREGATE
    )


# =============================================================================
# Segments Tools
# =============================================================================


@mcp.tool(tags={"read", "basic", "keila"})
async def list_all_segments(
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """List all segment records.

    Args:
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    data = await get_client().list_all_segments(
        get_user_token(),
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False,
    )
    return {"items": json_to_toon(data)}


@mcp.tool(tags={"read", "basic", "keila"})
async def get_segment_by_id(
    id: str,
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Get a single segment by its ID.

    Args:
        id: The unique ID of the segment.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    return await get_client().get_segment_by_id(
        id, get_user_token(), include_all_fields=include_all_fields
    )


@mcp.tool(tags={"write", "primary", "keila"})
async def create_segment(
    name: str,
    filter: SegmentFilter,
    ctx: Context = None,
) -> dict[str, Any]:
    """Create a new segment.

    Args:
        name: Name of the new segment.
        filter: Filter criteria object.
    """
    params = CreateSegmentParam(name=name, filter=filter)
    p = params.model_dump(exclude_unset=True, exclude_none=True)
    return await get_client().create_segment(
        p, get_user_token(), include_all_fields=ALLOW_ALL_AGGREGATE
    )


@mcp.tool(tags={"write", "primary", "keila"})
async def update_segment(
    id: str,
    name: Optional[str] = None,
    filter: Optional[SegmentFilter] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Update an existing segment.

    Args:
        id: The unique ID of the segment to update.
        name: Updated name of the segment.
        filter: Filter criteria object.
    """
    params = UpdateSegmentParam(id=id, name=name, filter=filter)
    p = params.model_dump(exclude_unset=True, exclude_none=True)
    p.pop("id", None)
    return await get_client().update_segment(
        id, p, get_user_token(), include_all_fields=ALLOW_ALL_AGGREGATE
    )


@mcp.tool(tags={"write", "basic", "keila"})
async def delete_segment_by_id(
    id: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """Delete a segment by its ID.

    Args:
        id: The unique ID of the segment to delete.
    """
    await get_client().delete_segment_by_id(id, get_user_token())
    return {"deleted": True, "id": id}


# =============================================================================
# Templates Tools
# =============================================================================


@mcp.tool(tags={"read", "basic", "keila"})
async def list_all_templates(
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """List all template records.

    Args:
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    data = await get_client().list_all_templates(
        get_user_token(),
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False,
    )
    return {"items": json_to_toon(data)}


@mcp.tool(tags={"read", "basic", "keila"})
async def get_template_by_id(
    id: str,
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Get a single template by its ID.

    Args:
        id: The unique ID of the template.
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    return await get_client().get_template_by_id(
        id, get_user_token(), include_all_fields=include_all_fields
    )


@mcp.tool(tags={"write", "primary", "keila"})
async def create_template(
    name: str,
    type: str,
    mjml_body: str = "",
    html_body: str = "",
    text_body: str = "",
    styles: str = "",
    assigns: Optional[TemplateAssigns] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Create a new template.

    Args:
        name: Name of the new template.
        type: text, html, mjml, or hybrid.
        mjml_body: MJML markup body.
        html_body: HTML body content.
        text_body: Plain text body.
        styles: CSS styles.
        assigns: Template variables (key-value object).
    """
    params = CreateTemplateParam(
        name=name, type=type, mjml_body=mjml_body, html_body=html_body,
        text_body=text_body, styles=styles, assigns=assigns,
    )
    p = params.model_dump(exclude_unset=True, exclude_none=True)
    return await get_client().create_template(
        p, get_user_token(), include_all_fields=ALLOW_ALL_AGGREGATE
    )


@mcp.tool(tags={"write", "primary", "keila"})
async def update_template(
    id: str,
    name: Optional[str] = None,
    type: Optional[str] = None,
    mjml_body: Optional[str] = None,
    html_body: Optional[str] = None,
    text_body: Optional[str] = None,
    styles: Optional[str] = None,
    assigns: Optional[TemplateAssigns] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Update an existing template.

    Args:
        id: The unique ID of the template to update.
        name: Updated name of the template.
        type: text, html, mjml, or hybrid.
        mjml_body: Updated MJML markup body.
        html_body: Updated HTML body.
        text_body: Updated plain text body.
        styles: Updated CSS styles.
        assigns: Template variables (key-value object).
    """
    params = UpdateTemplateParam(
        id=id, name=name, type=type, mjml_body=mjml_body,
        html_body=html_body, text_body=text_body, styles=styles,
        assigns=assigns,
    )
    p = params.model_dump(exclude_unset=True, exclude_none=True)
    p.pop("id", None)
    return await get_client().update_template(
        id, p, get_user_token(), include_all_fields=ALLOW_ALL_AGGREGATE
    )


@mcp.tool(tags={"write", "basic", "keila"})
async def delete_template_by_id(
    id: str,
    ctx: Context = None,
) -> dict[str, Any]:
    """Delete a template by its ID.

    Args:
        id: The unique ID of the template to delete.
    """
    await get_client().delete_template_by_id(id, get_user_token())
    return {"deleted": True, "id": id}


# =============================================================================
# Senders Tools
# =============================================================================


@mcp.tool(tags={"read", "basic", "keila"})
async def list_all_senders(
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """List all sender records.

    Args:
        include_all_fields: Default False (common fields only). Set True for all fields.
    """
    data = await get_client().list_all_senders(
        get_user_token(),
        include_all_fields=include_all_fields if ALLOW_ALL_AGGREGATE else False,
    )
    return {"items": json_to_toon(data)}


# =============================================================================
# Transactional Messages Tools
# =============================================================================


@mcp.tool(tags={"write", "primary", "keila"})
async def send_transactional_message(
    type: str,
    sender_id: str,
    recipient_email: str = "",
    recipient_name: str = "",
    cc: list[str] = [],
    bcc: list[str] = [],
    contact_id: str = "",
    external_contact_id: str = "",
    subject: str = "",
    text_body: str = "",
    html_body: str = "",
    mjml_body: str = "",
    mjml_content: Optional[ContentSlots] = None,
    html_content: Optional[ContentSlots] = None,
    text_content: Optional[ContentSlots] = None,
    assigns: Optional[MessageAssigns] = None,
    template_id: str = "",
    ctx: Context = None,
) -> dict[str, Any]:
    """Send a transactional message.

    Args:
        type: text, html, or mjml.
        sender_id: ID of the sender.
        recipient_email: Email address of the recipient.
        recipient_name: Name of the recipient.
        cc: List of CC recipient email addresses.
        bcc: List of BCC recipient email addresses.
        contact_id: ID of an existing contact.
        external_contact_id: External ID of a contact.
        subject: Subject of the message.
        text_body: Plain text body.
        html_body: HTML body.
        mjml_body: MJML markup body.
        mjml_content: Map of named MJML content slots.
        html_content: Map of named HTML content slots.
        text_content: Map of named text content slots.
        assigns: Template variables (key-value object).
        template_id: ID of the template to use.
    """
    params = TransactionalMessageParam(
        type=type, sender_id=sender_id,
        recipient_email=recipient_email, recipient_name=recipient_name,
        cc=cc, bcc=bcc, contact_id=contact_id,
        external_contact_id=external_contact_id, subject=subject,
        text_body=text_body, html_body=html_body, mjml_body=mjml_body,
        mjml_content=mjml_content, html_content=html_content,
        text_content=text_content, assigns=assigns,
        template_id=template_id,
    )
    p = params.model_dump(exclude_unset=True, exclude_none=True)
    for key in ("template_id", "contact_id", "external_contact_id"):
        if key in p and not p[key]:
            del p[key]
    for key in ("cc", "bcc", "recipient_email", "recipient_name"):
        if key in p and not p[key]:
            del p[key]
    return await get_client().send_transactional_message(
        p, get_user_token(), include_all_fields=ALLOW_ALL_AGGREGATE
    )


@mcp.tool(tags={"write", "primary", "keila"})
async def render_transactional_message(
    type: str,
    sender_id: str,
    recipient_email: str = "",
    recipient_name: str = "",
    cc: list[str] = [],
    bcc: list[str] = [],
    contact_id: str = "",
    external_contact_id: str = "",
    subject: str = "",
    text_body: str = "",
    html_body: str = "",
    mjml_body: str = "",
    mjml_content: Optional[ContentSlots] = None,
    html_content: Optional[ContentSlots] = None,
    text_content: Optional[ContentSlots] = None,
    assigns: Optional[MessageAssigns] = None,
    template_id: str = "",
    ctx: Context = None,
) -> dict[str, Any]:
    """Render a transactional message without sending it.

    Args:
        type: text, html, or mjml.
        sender_id: ID of the sender.
        recipient_email: Email address of the recipient.
        recipient_name: Name of the recipient.
        cc: List of CC recipient email addresses.
        bcc: List of BCC recipient email addresses.
        contact_id: ID of an existing contact.
        external_contact_id: External ID of a contact.
        subject: Subject of the message.
        text_body: Plain text body.
        html_body: HTML body.
        mjml_body: MJML markup body.
        mjml_content: Map of named MJML content slots.
        html_content: Map of named HTML content slots.
        text_content: Map of named text content slots.
        assigns: Template variables (key-value object).
        template_id: ID of the template to use.
    """
    params = TransactionalMessageParam(
        type=type, sender_id=sender_id,
        recipient_email=recipient_email, recipient_name=recipient_name,
        cc=cc, bcc=bcc, contact_id=contact_id,
        external_contact_id=external_contact_id, subject=subject,
        text_body=text_body, html_body=html_body, mjml_body=mjml_body,
        mjml_content=mjml_content, html_content=html_content,
        text_content=text_content, assigns=assigns,
        template_id=template_id,
    )
    p = params.model_dump(exclude_unset=True, exclude_none=True)
    for key in ("template_id", "contact_id", "external_contact_id"):
        if key in p and not p[key]:
            del p[key]
    for key in ("cc", "bcc", "recipient_email", "recipient_name"):
        if key in p and not p[key]:
            del p[key]
    return await get_client().render_transactional_message(
        p, get_user_token(), include_all_fields=ALLOW_ALL_AGGREGATE
    )


# =============================================================================
# Entry Point
# =============================================================================


def main():
    if not os.getenv("KEILA_BASE_URL"):
        print("ERROR: KEILA_BASE_URL environment variable is required", file=sys.stderr)
        print("Example: export KEILA_BASE_URL=http://keila-app:4000", file=sys.stderr)
        sys.exit(1)

    port_env = os.getenv("MCP_SERVER_PORT")
    if not port_env:
        print("ERROR: MCP_SERVER_PORT environment variable is required", file=sys.stderr)
        print("Example: export MCP_SERVER_PORT=5721", file=sys.stderr)
        sys.exit(1)

    host = "0.0.0.0"
    port = int(port_env)
    path = "/mcp"
    if IS_STATEFUL:
        app = mcp.http_app(path=path)
    else:
        app = mcp.http_app(path=path, stateless_http=True)
    app = AuthMiddleware(app)
    print(f"Starting Keila MCP server on http://{host}:{port}{path}", file=sys.stderr)
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
