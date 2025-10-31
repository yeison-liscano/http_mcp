from http import HTTPStatus

from starlette.testclient import TestClient

from tests.app.main import mcp_server, mount_mcp_server


def test_http() -> None:
    app = mount_mcp_server(mcp_server)
    client = TestClient(app)
    response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "tools/list", "id": 1})
    assert response.status_code == HTTPStatus.OK


def test_http_list_only_public_tools() -> None:
    app = mount_mcp_server(mcp_server)
    client = TestClient(app)
    response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "tools/list", "id": 1})
    assert response.status_code == HTTPStatus.OK
    response_json = response.json()
    assert response_json == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [
                {
                    "name": "get_weather",
                    "title": "Get Weather",
                    "description": "Get the current weather in a given location.",
                    "inputSchema": {
                        "properties": {
                            "location": {
                                "description": "The location to get the weather for",
                                "title": "Location",
                                "type": "string",
                            },
                            "unit": {
                                "default": "celsius",
                                "description": "The unit of temperature",
                                "title": "Unit",
                                "type": "string",
                            },
                        },
                        "required": ["location"],
                        "title": "get_weatherArguments",
                        "type": "object",
                    },
                    "outputSchema": {
                        "properties": {
                            "weather": {
                                "description": "The weather in the given location",
                                "title": "Weather",
                                "type": "string",
                            },
                        },
                        "required": ["weather"],
                        "title": "get_weatherOutput",
                        "type": "object",
                    },
                    "annotations": {
                        "title": "Get Weather",
                        "readOnlyHint": False,
                        "destructiveHint": False,
                        "idempotentHint": True,
                        "openWorldHint": True,
                    },
                    "meta": None,
                },
                {
                    "name": "get_time",
                    "title": "Get Time",
                    "description": "Get the current time.",
                    "inputSchema": {
                        "properties": {},
                        "title": "get_timeArguments",
                        "type": "object",
                    },
                    "outputSchema": {
                        "properties": {
                            "time": {
                                "description": "The current time",
                                "title": "Time",
                                "type": "string",
                            },
                        },
                        "required": ["time"],
                        "title": "get_timeOutput",
                        "type": "object",
                    },
                    "annotations": {
                        "title": "Get Time",
                        "readOnlyHint": False,
                        "destructiveHint": False,
                        "idempotentHint": True,
                        "openWorldHint": True,
                    },
                    "meta": None,
                },
                {
                    "name": "tool_that_access_request",
                    "title": "Tool That Access Request",
                    "description": "Access the request.",
                    "inputSchema": {
                        "properties": {
                            "username": {
                                "description": "The username of the user",
                                "title": "Username",
                                "type": "string",
                            },
                        },
                        "required": ["username"],
                        "title": "tool_that_access_requestArguments",
                        "type": "object",
                    },
                    "outputSchema": {
                        "properties": {
                            "message": {
                                "description": "The message to the user",
                                "title": "Message",
                                "type": "string",
                            },
                        },
                        "required": ["message"],
                        "title": "tool_that_access_requestOutput",
                        "type": "object",
                    },
                    "annotations": {
                        "title": "Tool That Access Request",
                        "readOnlyHint": False,
                        "destructiveHint": False,
                        "idempotentHint": True,
                        "openWorldHint": True,
                    },
                    "meta": None,
                },
                {
                    "name": "get_called_tools",
                    "title": "Get Called Tools",
                    "description": "Get the list of called tools.",
                    "inputSchema": {
                        "properties": {},
                        "title": "get_called_toolsArguments",
                        "type": "object",
                    },
                    "outputSchema": {
                        "properties": {
                            "called_tools": {
                                "description": "The list of called tools",
                                "items": {"type": "string"},
                                "title": "Called Tools",
                                "type": "array",
                            },
                        },
                        "required": ["called_tools"],
                        "title": "get_called_toolsOutput",
                        "type": "object",
                    },
                    "annotations": {
                        "title": "Get Called Tools",
                        "readOnlyHint": False,
                        "destructiveHint": False,
                        "idempotentHint": True,
                        "openWorldHint": True,
                    },
                    "meta": None,
                },
            ],
            "nextCursor": "",
        },
    }
