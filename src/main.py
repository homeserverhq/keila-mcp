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
    id: Optional[str] = Field(
        default=None,
        description="Unique block ID (e.g. ff0011). Required when updating an existing block; omit for new blocks.",
    )
    type: str = Field(
        description="Block type: paragraph, header, list, quote, button, image, layout, separator, or socialIcons",
    )
    data: BlockData = Field(
        default_factory=BlockData,
        description=(
            "Block-specific data keyed by type. Examples: "
            'paragraph: {"text": "Hello"}; '
            'header: {"text": "Title", "level": 1}; '
            'list: {"items": [{"content": "Item 1", "meta": {}}], "style": "unordered"}; '
            'quote: {"text": "Quote", "caption": "Author", "alignment": "left"}; '
            'button: {"label": "Buy", "url": "https://example.com", "centered": true}; '
            'image: {"image": {"src": "https://example.com/img.png"}, "caption": "A caption", "url": "https://example.com"}; '
            'layout: {"blocks": [], "columns": 2, "ratio": "1-1"}; '
            'separator: {}; '
            'socialIcons: {"social_icons": [], "alignment": "center", "size": 32}'
        ),
    )


class CampaignJsonBody(BaseModel):
    blocks: list[ContentBlock] = Field(
        default_factory=list,
        description=(
            "List of content blocks that form the campaign body. "
            'Example: [{"type": "paragraph", "data": {"text": "Hello"}}]'
        ),
    )


class ContentSlots(BaseModel):
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def _validate_values(self):
        for k, v in (self.__pydantic_extra__ or {}).items():
            if not isinstance(v, str):
                raise ValueError(f"Content slot '{k}' value must be a string, got {type(v).__name__}")
        return self


class FormFieldAllowedValue(BaseModel):
    label: str = Field(description="Display label shown to the submitter (e.g. \"Option A\")")
    value: str = Field(description="Stored value for the option (e.g. option_a)")


class FormField(BaseModel):
    field: str = Field(
        description="Contact field this form field maps to: email, first_name, last_name, or data",
    )
    required: Optional[bool] = Field(
        default=None,
        description="true or false. Whether the field must be filled before the form can be submitted",
    )
    cast: Optional[bool] = Field(
        default=None,
        description="true or false. Whether the submitted value is cast to the field type (e.g. integer) when stored",
    )
    key: Optional[str] = Field(
        default=None,
        description='Data key to store the value under when field is "data" (e.g. city)',
    )
    type: Optional[str] = Field(
        default=None,
        description="Input type: email, string, integer, boolean, enum, tags, or array",
    )
    label: Optional[str] = Field(
        default=None,
        description="Label displayed above the input (e.g. City)",
    )
    placeholder: Optional[str] = Field(
        default=None,
        description="Placeholder text shown inside the input (e.g. Berlin)",
    )
    description: Optional[str] = Field(
        default=None,
        description="Helper text displayed below the input (e.g. We only use this to send you news)",
    )
    allowed_values: Optional[list[FormFieldAllowedValue]] = Field(
        default=None,
        description='List of selectable options (label/value pairs) when type is "enum" (e.g. [{"label": "Option A", "value": "a"}])',
    )


class FormSettings(BaseModel):
    captcha_required: Optional[bool] = Field(
        default=None,
        description="true or false. Require solving a CAPTCHA before the form is accepted",
    )
    double_opt_in_required: Optional[bool] = Field(
        default=None,
        description="true or false. Require the contact to confirm their email before the contact is created",
    )
    double_opt_in_subject: Optional[str] = Field(
        default=None,
        description="Subject of the double opt-in confirmation email (e.g. Please confirm your subscription)",
    )
    double_opt_in_markdown_body: Optional[str] = Field(
        default=None,
        description='Markdown body of the confirmation email. Supports the {{ double_opt_in_link }} variable (e.g. "Click [here]({{ double_opt_in_link }}) to confirm")',
    )
    double_opt_in_message: Optional[str] = Field(
        default=None,
        description="Message shown on the form after submission while double opt-in confirmation is pending",
    )
    double_opt_in_url: Optional[str] = Field(
        default=None,
        description="URL to redirect to after a form was submitted and double opt-in is required",
    )
    csrf_disabled: Optional[bool] = Field(
        default=None,
        description="true or false. Disable CSRF protection on the public form submission endpoint",
    )
    intro_text: Optional[str] = Field(
        default=None,
        description="Introductory text shown above the form fields",
    )
    fine_print: Optional[str] = Field(
        default=None,
        description="Fine print text shown below the form fields",
    )
    body_bg_color: Optional[str] = Field(
        default=None,
        description="Background color of the page behind the form as a hex value (e.g. #f0f0f0)",
    )
    form_bg_color: Optional[str] = Field(
        default=None,
        description="Background color of the form itself as a hex value (e.g. #ffffff)",
    )
    text_color: Optional[str] = Field(
        default=None,
        description="Text color as a hex value (e.g. #333333)",
    )
    submit_label: Optional[str] = Field(
        default=None,
        description="Label of the submit button (e.g. Subscribe)",
    )
    submit_bg_color: Optional[str] = Field(
        default=None,
        description="Submit button background color as a hex value (e.g. #0088cc)",
    )
    submit_text_color: Optional[str] = Field(
        default=None,
        description="Submit button text color as a hex value (e.g. #ffffff)",
    )
    input_bg_color: Optional[str] = Field(
        default=None,
        description="Input field background color as a hex value (e.g. #ffffff)",
    )
    input_border_color: Optional[str] = Field(
        default=None,
        description="Input field border color as a hex value (e.g. #cccccc)",
    )
    input_text_color: Optional[str] = Field(
        default=None,
        description="Input field text color as a hex value (e.g. #333333)",
    )
    success_text: Optional[str] = Field(
        default=None,
        description="Message shown after a successful form submission",
    )
    success_url: Optional[str] = Field(
        default=None,
        description='URL to redirect to after a successful submission. Supports Liquid with the contact assign present (e.g. https://example.com/thank-you/{{ contact.id }})',
    )
    failure_text: Optional[str] = Field(
        default=None,
        description="Message shown after a failed form submission",
    )
    failure_url: Optional[str] = Field(
        default=None,
        description="URL to redirect to after a failed form submission",
    )
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
    page: int = 0,
    page_size: int = 50,
    filter: Optional[SegmentFilter] = None,
    include_all_fields: bool = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """List all contact records.

    Args:
        page: Page number, 0 (first page) or higher. (e.g. 0) (Default: 0).
        page_size: Records per page, 1 or higher. (e.g. 50) (Default: 50).
        filter: MongoDB-style filter object (e.g. {"email": {"$like": "%keila.io"}} or {"status": "active"}). Operators: $not, $or, $gt, $gte, $lt, $lte, $empty, $in, or $like; custom data fields via data.<field> (e.g. {"data.city": {"$in": ["Munich", "Berlin"]}}).
        include_all_fields: Default False (common fields only). Set True for all fields.
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
        id: Contact ID (e.g. nc_12345), email address, or external ID, depending on id_type.
        id_type: id, email, or external_id (Default: id).
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
        email: Email address of the new contact (e.g. jane.doe@example.com).
        first_name: First name (e.g. Jane).
        last_name: Last name (e.g. Doe).
        external_id: External ID for cross-referencing (e.g. customer-1234).
        status: active, unsubscribed, or unreachable (Default: active).
        data: Custom data object; values may be strings, numbers, booleans, or lists (e.g. {"city": "Munich", "interests": ["chess", "books"]}).
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
        id: Contact ID (e.g. nc_12345), email address, or external ID, depending on id_type.
        id_type: id, email, or external_id (Default: id).
        email: Updated email address (e.g. jane.doe@example.com).
        first_name: Updated first name (e.g. Jane).
        last_name: Updated last name (e.g. Doe).
        external_id: Updated external ID (e.g. customer-1234).
        status: active, unsubscribed, or unreachable.
        data: Custom data object; values may be strings, numbers, booleans, or lists (e.g. {"city": "Munich", "interests": ["chess", "books"]}).
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
        id: Contact ID (e.g. nc_12345), email address, or external ID, depending on id_type.
        id_type: id, email, or external_id (Default: id).
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
        id: Contact ID (e.g. nc_12345), email address, or external ID, depending on id_type.
        data: Custom data object to shallow-merge into the contact's existing data (e.g. {"city": "Munich"}).
        id_type: id, email, or external_id (Default: id).
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
        id: Contact ID (e.g. nc_12345), email address, or external ID, depending on id_type.
        data: Custom data object that fully replaces the contact's existing data (e.g. {"tags": ["test"]}).
        id_type: id, email, or external_id (Default: id).
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
        id: Campaign ID (e.g. nmc_12345).
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
        subject: Subject line of the campaign (e.g. Our Space Book is Now Available!).
        settings_type: markdown, text, block, mjml, or html.
        text_body: Plain text body; supports Liquid (e.g. "Hi {{ contact.first_name }}, thanks for your order").
        json_body: Structured block content; use when settings_type is "block" (e.g. {"blocks": [{"type": "paragraph", "data": {"text": "Hello"}}]}).
        mjml_body: MJML markup body (e.g. "<mjml><mj-body><mj-section><mj-column><mj-text>Hello</mj-text></mj-column></mj-section></mj-body></mjml>").
        html_body: HTML body (e.g. "<p>Hi {{ contact.first_name }}!</p>").
        mjml_content: Map of named MJML content slots for templates with <keila-content> tags (e.g. {"main": "<mj-text>Hi</mj-text>"}).
        html_content: Map of named HTML content slots (e.g. {"main": "<p>Hi</p>"}).
        text_content: Map of named text content slots (e.g. {"main": "Hi"}).
        data: Custom campaign data available as campaign.data.<key> in Liquid (e.g. {"books": [{"title": "Space Book"}]}).
        template_id: Template ID (e.g. ntpl_12345).
        sender_id: Sender ID (e.g. nms_12345).
        segment_id: Target segment ID (e.g. nsgm_12345).
        preview_text: Text shown after the subject line (e.g. Hello, I am a preview campaign!).
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
        id: Campaign ID (e.g. nmc_12345).
        subject: Updated subject line.
        text_body: Updated plain text body; supports Liquid.
        json_body: Structured block content; use when settings_type is "block" (e.g. {"blocks": [{"type": "paragraph", "data": {"text": "Hello"}}]}).
        mjml_body: Updated MJML markup body.
        html_body: Updated HTML body.
        mjml_content: Map of named MJML content slots (e.g. {"main": "<mj-text>Hi</mj-text>"}).
        html_content: Map of named HTML content slots (e.g. {"main": "<p>Hi</p>"}).
        text_content: Map of named text content slots (e.g. {"main": "Hi"}).
        data: Custom campaign data available as campaign.data.<key> in Liquid (e.g. {"books": [{"title": "Space Book"}]}).
        settings_type: markdown, text, block, mjml, or html.
        template_id: Updated template ID (e.g. ntpl_12345).
        sender_id: Updated sender ID (e.g. nms_12345).
        segment_id: Updated segment ID (e.g. nsgm_12345).
        preview_text: Updated preview text shown after the subject line.
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
        id: Campaign ID (e.g. nmc_12345).
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
        id: Campaign ID (e.g. nmc_12345).
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
        id: Campaign ID (e.g. nmc_12345).
        scheduled_for: ISO 8601 datetime with timezone offset, e.g. 2026-06-22T15:00:00-04:00 (UTC example: 2026-06-22T19:00:00+00:00). Must be in the future.
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
        id: Form ID (e.g. nfrm_12345).
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
        name: Name of the new form (e.g. Newsletter Signup).
        sender_id: Sender ID used for confirmation emails (e.g. nms_12345).
        template_id: Template ID used for confirmation emails (e.g. ntpl_12345).
        settings: Form settings object (see FormSettings), e.g. {"double_opt_in_required": false}.
        fields: List of form field configurations (see FormField), e.g. [{"field": "email", "required": true, "cast": true}].
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
        id: Form ID (e.g. nfrm_12345).
        name: Updated name of the form.
        sender_id: Updated sender ID for confirmation emails (e.g. nms_12345).
        template_id: Updated template ID for confirmation emails (e.g. ntpl_12345).
        settings: Form settings object (see FormSettings), e.g. {"double_opt_in_required": false}.
        fields: List of form field configurations (see FormField), e.g. [{"field": "email", "required": true, "cast": true}].
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
        id: Form ID (e.g. nfrm_12345).
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
        id: Form ID (e.g. nfrm_12345).
        email: Email address of the contact (e.g. jane.doe@example.com).
        first_name: First name (e.g. Jane).
        last_name: Last name (e.g. Doe).
        external_id: External ID for cross-referencing (e.g. customer-1234).
        status: active, unsubscribed, or unreachable (Default: active).
        data: Custom data object; values may be strings, numbers, booleans, or lists (e.g. {"city": "Munich", "interests": ["chess", "books"]}).
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
        id: Segment ID (e.g. nsgm_12345).
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
        name: Name of the new segment (e.g. Rocket scientists and book enthusiasts).
        filter: MongoDB-style filter object (e.g. {"email": {"$like": "%keila.io"}} or {"status": "active"}). Operators: $not, $or, $gt, $gte, $lt, $lte, $empty, $in, or $like; custom data fields via data.<field> (e.g. {"data.city": {"$in": ["Munich", "Berlin"]}}).
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
        id: Segment ID (e.g. nsgm_12345).
        name: Updated name of the segment.
        filter: MongoDB-style filter object (e.g. {"email": {"$like": "%keila.io"}} or {"status": "active"}). Operators: $not, $or, $gt, $gte, $lt, $lte, $empty, $in, or $like; custom data fields via data.<field>.
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
        id: Segment ID (e.g. nsgm_12345).
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
        id: Template ID (e.g. ntpl_12345).
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
        name: Name of the new template (e.g. Welcome Email).
        type: text, html, mjml, or hybrid.
        mjml_body: MJML markup body; declare content slots with <keila-content name="slot"> (e.g. "<mjml><mj-body><keila-content name=\"main\"><mj-text>Hi {{ contact.first_name }}</mj-text></keila-content></mj-body></mjml>").
        html_body: HTML body; declare content slots with <keila-content name="slot"> (e.g. "<html><body><keila-content name=\"main\"><p>Hi {{ contact.first_name }}</p></keila-content></body></html>").
        text_body: Plain text body; declare content slots with <keila-content name="slot"> (e.g. "<keila-content name=\"main\">Hi {{ contact.first_name }}</keila-content>").
        styles: CSS styles applied when the template is rendered.
        assigns: Template variables available as assign.<key> in Liquid (e.g. {"company_name": "Acme"}).
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
        id: Template ID (e.g. ntpl_12345).
        name: Updated name of the template.
        type: text, html, mjml, or hybrid.
        mjml_body: Updated MJML markup body; declare content slots with <keila-content name="slot">.
        html_body: Updated HTML body; declare content slots with <keila-content name="slot">.
        text_body: Updated plain text body; declare content slots with <keila-content name="slot">.
        styles: Updated CSS styles applied when the template is rendered.
        assigns: Template variables available as assign.<key> in Liquid (e.g. {"company_name": "Acme"}).
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
        id: Template ID (e.g. ntpl_12345).
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
        sender_id: Sender ID (e.g. nms_12345).
        recipient_email: Email address of the recipient (e.g. jane.doe@example.com).
        recipient_name: Name of the recipient (e.g. Jane Doe).
        cc: List of CC recipient email addresses (e.g. ["john@example.com"]) (Default: []).
        bcc: List of BCC recipient email addresses (e.g. ["jane@example.com"]) (Default: []).
        contact_id: Contact ID to attach the message to (e.g. nc_12345).
        external_contact_id: External ID of a contact (e.g. customer-1234).
        subject: Subject of the message (e.g. Your order is confirmed).
        text_body: Plain text body; supports Liquid (e.g. "Hi {{ contact.first_name }}, thanks for your order").
        html_body: HTML body (e.g. "<p>Hi {{ contact.first_name }}, thanks for your order</p>").
        mjml_body: MJML markup body (e.g. "<mjml><mj-body><mj-section><mj-column><mj-text>Hi!</mj-text></mj-column></mj-section></mj-body></mjml>").
        mjml_content: Map of named MJML content slots for templates with <keila-content> tags (e.g. {"main": "<mj-text>Hi {{ contact.first_name }}</mj-text>"}).
        html_content: Map of named HTML content slots (e.g. {"main": "<p>Hi {{ contact.first_name }}</p>"}).
        text_content: Map of named text content slots (e.g. {"main": "Hi {{ contact.first_name }}"}). (Default: {})
        assigns: Values made available to Liquid interpolation in the subject and body (e.g. {"magic_link": "https://example.com/reset?token=abc123"}).
        template_id: Template ID to render the message with (e.g. ntpl_12345).
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
        sender_id: Sender ID (e.g. nms_12345).
        recipient_email: Email address of the recipient (e.g. jane.doe@example.com).
        recipient_name: Name of the recipient (e.g. Jane Doe).
        cc: List of CC recipient email addresses (e.g. ["john@example.com"]) (Default: []).
        bcc: List of BCC recipient email addresses (e.g. ["jane@example.com"]) (Default: []).
        contact_id: Contact ID to attach the message to (e.g. nc_12345).
        external_contact_id: External ID of a contact (e.g. customer-1234).
        subject: Subject of the message (e.g. Your order is confirmed).
        text_body: Plain text body; supports Liquid (e.g. "Hi {{ contact.first_name }}, thanks for your order").
        html_body: HTML body (e.g. "<p>Hi {{ contact.first_name }}, thanks for your order</p>").
        mjml_body: MJML markup body (e.g. "<mjml><mj-body><mj-section><mj-column><mj-text>Hi!</mj-text></mj-column></mj-section></mj-body></mjml>").
        mjml_content: Map of named MJML content slots for templates with <keila-content> tags (e.g. {"main": "<mj-text>Hi {{ contact.first_name }}</mj-text>"}).
        html_content: Map of named HTML content slots (e.g. {"main": "<p>Hi {{ contact.first_name }}</p>"}).
        text_content: Map of named text content slots (e.g. {"main": "Hi {{ contact.first_name }}"}). (Default: {})
        assigns: Values made available to Liquid interpolation in the subject and body (e.g. {"magic_link": "https://example.com/reset?token=abc123"}).
        template_id: Template ID to render the message with (e.g. ntpl_12345).
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
