from pydantic import BaseModel

from http_mcp.server import MCPServer
from http_mcp.tools import Tool, ToolArguments


class DummyModel(BaseModel):
    argument_1: int
    argument_2: str


def dummy_tool(_arg: ToolArguments[DummyModel, None]) -> DummyModel:
    raise NotImplementedError


DUMMY_TOOL = Tool(
    func=dummy_tool,
    input=DummyModel,
    output=DummyModel,
)

DUMMY_SERVER = MCPServer(
    name="test",
    version="1.0.0",
    tools=(DUMMY_TOOL,),
)


class TestToolArguments(BaseModel):
    question: str


class TestToolOutput(BaseModel):
    answer: str
