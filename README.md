# Base Python Project

This project is a base python project environment configuration using Nix.

## Features

- **Dependency Management**: Uses `uv` for fast and efficient package management.
- **Linting**: Integrated with `Ruff` for code formatting and linting.
- **Type Checking**: Uses `Mypy` for static type checking.
- **Environment Management**: Configured to work with `direnv` for automatic environment loading.

## Getting Started

### Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/)

### Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd base_python_project
    uv venv --python 3.13
    source .venv/bin/activate
    # install dependencies
    uv sync
    # adding dependencies to the project
    uv add <dependency>
    # removing dependencies from the project
    uv remove <dependency>
    # updating dependencies to the latest version
    uv update <dependency>
    # updating all dependencies to the latest version
    ```



## Usage

To run the main application:

```bash
python -m project.main
```

Or using the project script:

```bash
project-run
```

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
