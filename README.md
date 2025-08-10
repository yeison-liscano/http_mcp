# Simple HTTP MCP Server

This project provides a lightweight server implementation for the Model Context Protocol (MCP) over HTTP. It allows you to expose Python functions as "tools" that can be discovered and executed remotely via a JSON-RPC interface. It is thought to be used with an Starlette or FastAPI application (see [app/main.py](app/main.py)).

## How to test with Gemini Cli

1.  **Install dependencies:**
    ```bash
    uv sync
    uv run run-app
    ```

2.  **Test the server:**

    Note: you should be located on the root folder of the project so gemini config is used.

    ```bash
    gemini
    /mcp # This should show the tools available
    ```

Example:

![Example](assets/gemini_test.png)

## Features

- **MCP Protocol Compliant**: Implements the MCP specification for tool discovery and execution.
- **HTTP Transport**: Uses HTTP POST for communication.
- **Async Support**: Built on `Starlette` or `FastAPI` for asynchronous request handling.
- **Type-Safe**: Leverages `Pydantic` for robust data validation and serialization.
- **Dependency Management**: Uses `uv` for fast and efficient package management.
- **Linting**: Integrated with `Ruff` for code formatting and linting.
- **Type Checking**: Uses `Mypy` for static type checking.

## Getting Started

### Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/)

### Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd simple-http-mcp
    ```

2.  **Create a virtual environment and install dependencies:**
    ```bash
    uv venv
    source .venv/bin/activate
    uv sync
    ```

## Usage

For usage examples, please refer to the tests in the `tests/` directory.

## Development

This project uses several tools to ensure code quality.

### Linting

To check for linting errors, run:

```bash
ruff check .
```

To automatically fix linting errors, run:

```bash
ruff check . --fix
```

### Type Checking

To run the static type checker, use:

```bash
mypy .
```