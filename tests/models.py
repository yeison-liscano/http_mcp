from pydantic import BaseModel


class TestToolArguments(BaseModel):
    question: str


class TestToolOutput(BaseModel):
    answer: str
