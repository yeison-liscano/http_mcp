from typing import Literal

from pydantic import BaseModel


class TextContent(BaseModel):
    text: str
    type: Literal["text"] = "text"
