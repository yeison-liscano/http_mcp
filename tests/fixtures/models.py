from pydantic import BaseModel

from http_mcp.server import MCPServer
from http_mcp.types import Arguments, Tool


class DummyModel(BaseModel):
    argument_1: int
    argument_2: str


def dummy_tool(_arg: Arguments[DummyModel]) -> DummyModel:
    raise NotImplementedError


DUMMY_TOOL = Tool(
    func=dummy_tool,
    inputs=DummyModel,
    output=DummyModel,
)

DUMMY_SERVER = MCPServer(
    "test",
    "1.0.0",
    (DUMMY_TOOL,),
)


class TestToolArguments(BaseModel):
    question: str


class TestToolOutput(BaseModel):
    answer: str
