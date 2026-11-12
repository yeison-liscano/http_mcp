"""Elicitation requests and responses used by multi round-trip calls."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

type ElicitationMode = Literal["form", "url"]


def supported_elicitation_modes(declared: object) -> frozenset[ElicitationMode]:
    """Interpret the client's declaration, including the implicit form baseline."""
    if not isinstance(declared, dict):
        return frozenset()
    if not declared:
        return frozenset(("form",))
    modes: tuple[ElicitationMode, ...] = ("form", "url")
    return frozenset(mode for mode in modes if isinstance(declared.get(mode), dict))


class _Schema(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        frozen=True,
        allow_inf_nan=False,
    )


class _Field(_Schema):
    title: str | None = None
    description: str | None = None


class StringField(_Field):
    type: Literal["string"] = "string"
    min_length: int | None = Field(
        default=None,
        serialization_alias="minLength",
        validation_alias="minLength",
        ge=0,
    )
    max_length: int | None = Field(
        default=None,
        serialization_alias="maxLength",
        validation_alias="maxLength",
        ge=0,
    )
    format: Literal["email", "uri", "date", "date-time"] | None = None
    default: StrictStr | None = None


class NumberField(_Field):
    type: Literal["number", "integer"] = "number"
    minimum: StrictInt | StrictFloat | None = None
    maximum: StrictInt | StrictFloat | None = None
    default: StrictInt | StrictFloat | None = None


class BooleanField(_Field):
    type: Literal["boolean"] = "boolean"
    default: StrictBool | None = None


class ChoiceOption(_Schema):
    const: str
    title: str


class ChoiceField(_Field):
    type: Literal["string"] = "string"
    enum: tuple[str, ...]
    enum_names: tuple[str, ...] | None = Field(
        default=None,
        serialization_alias="enumNames",
        validation_alias="enumNames",
    )
    default: StrictStr | None = None


class TitledChoiceField(_Field):
    type: Literal["string"] = "string"
    one_of: tuple[ChoiceOption, ...] = Field(serialization_alias="oneOf", validation_alias="oneOf")
    default: StrictStr | None = None


class ChoiceItems(_Schema):
    type: Literal["string"] = "string"
    enum: tuple[str, ...]


class TitledChoiceItems(_Schema):
    any_of: tuple[ChoiceOption, ...] = Field(serialization_alias="anyOf", validation_alias="anyOf")


class MultiChoiceField(_Field):
    type: Literal["array"] = "array"
    items: ChoiceItems | TitledChoiceItems
    min_items: int | None = Field(
        default=None,
        serialization_alias="minItems",
        validation_alias="minItems",
        ge=0,
    )
    max_items: int | None = Field(
        default=None,
        serialization_alias="maxItems",
        validation_alias="maxItems",
        ge=0,
    )
    default: tuple[str, ...] | None = None


type FormField = (
    StringField | NumberField | BooleanField | ChoiceField | TitledChoiceField | MultiChoiceField
)


class ElicitationSchema(_Schema):
    type: Literal["object"] = "object"
    schema_uri: str | None = Field(
        default=None,
        serialization_alias="$schema",
        validation_alias="$schema",
    )
    properties: dict[str, FormField]
    required: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _required_properties_exist(self) -> ElicitationSchema:
        if not set(self.required).issubset(self.properties):
            message = "Required elicitation fields must be declared in properties"
            raise ValueError(message)
        return self


class FormElicitation(_Schema):
    mode: Literal["form"] = "form"
    message: str
    requested_schema: ElicitationSchema = Field(
        serialization_alias="requestedSchema",
        validation_alias="requestedSchema",
    )


class UrlElicitation(_Schema):
    mode: Literal["url"] = "url"
    message: str
    url: str

    @model_validator(mode="after")
    def _valid_url(self) -> UrlElicitation:
        # Validate without normalizing the URL the application sends to the user.
        AnyUrl(self.url)
        if any(char.isspace() or ord(char) < 32 for char in self.url):  # noqa: PLR2004
            message = "Elicitation URL must not contain whitespace or control characters"
            raise ValueError(message)
        return self


class ElicitationRequest(_Schema):
    method: Literal["elicitation/create"] = "elicitation/create"
    params: FormElicitation | UrlElicitation


type ElicitationValue = StrictStr | StrictInt | StrictFloat | StrictBool | list[StrictStr]


class AcceptedElicitation(_Schema):
    action: Literal["accept"] = "accept"
    # URL acceptance carries no form content.
    content: dict[str, ElicitationValue] | None = None

    @field_validator("content", mode="before")
    @classmethod
    def _content_is_not_null(cls, value: object) -> object:
        if value is None:
            message = "Accepted elicitation content must be an object when present"
            raise ValueError(message)
        return value


class DeclinedElicitation(_Schema):
    action: Literal["decline"] = "decline"


class CancelledElicitation(_Schema):
    action: Literal["cancel"] = "cancel"


type ElicitationResponse = Annotated[
    AcceptedElicitation | DeclinedElicitation | CancelledElicitation,
    Field(discriminator="action"),
]


class InputRequired(_Schema):
    """Return from a tool or prompt to request input before a separate retry."""

    input_requests: dict[str, ElicitationRequest] = Field(min_length=1)
    request_state: StrictStr | None = None


class RetryRequired(_Schema):
    """A continuation carrying state without requesting input from the client."""

    request_state: StrictStr
