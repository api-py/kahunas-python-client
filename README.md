# Kahunas Python Client

Python client library, CLI, and MCP server for the [Kahunas](https://kahunas.io) fitness coaching platform.

## Features

- **Python Client** — Async HTTP client (`httpx`) with Pydantic v2 models, automatic token refresh, and retry logic
- **MCP Server** — Stdio-based [Model Context Protocol](https://modelcontextprotocol.io/) server exposing all Kahunas features as tools for AI assistants
- **CLI** — Command-line interface with rich terminal output for managing clients, workouts, exercises, and exports
- **Data Export** — Export all client data (profiles, check-ins, progress photos, workouts, habits, chat history) to Excel files with organized directory structure
- **Auto Re-authentication** — Tokens are automatically refreshed when they expire

## Requirements

- Python 3.12+
- A Kahunas coaching account (email & password)

## Installation

```bash
pip install kahunas-client
```

Or install from source:

```bash
git clone https://github.com/your-org/kahunas-python-client.git
cd kahunas-python-client
pip install -e ".[dev]"
```

## Passing Credentials

The client supports multiple ways to provide your Kahunas credentials, in order of priority:

### 1. Environment Variables

```bash
export KAHUNAS_EMAIL="you@example.com"
export KAHUNAS_PASSWORD="your-password"
```

### 2. `.env` File

Create a `.env` file in your project root:

```
KAHUNAS_EMAIL=you@example.com
KAHUNAS_PASSWORD=your-password
```

### 3. YAML Config File

```yaml
# config.yaml
email: you@example.com
password: your-password
timeout: 60.0
```

Point to it via env var:

```bash
export KAHUNAS_CONFIG_FILE=config.yaml
```

### 4. CLI Flags

```bash
kahunas --email you@example.com --password your-password workouts list
```

### 5. Direct Token (Advanced)

If you already have an auth token, skip the login flow entirely:

```bash
export KAHUNAS_AUTH_TOKEN="your-744-character-token"
```

## Using as a Python Library

```python
import asyncio
from kahunas_client.client import KahunasClient
from kahunas_client.config import KahunasConfig

async def main():
    config = KahunasConfig(
        email="you@example.com",
        password="your-password",
    )

    async with KahunasClient(config) as client:
        # List workout programs
        programs = await client.list_workout_programs()
        for p in programs.workout_plan:
            print(f"{p.title} — {p.days} days")

        # Search exercises
        exercises = await client.search_exercises("squat")
        for ex in exercises:
            print(f"{ex.exercise_name} ({ex.exercise_type})")

        # List clients
        resp = await client.list_clients()
        print(resp.json())

        # Get client progress charts
        resp = await client.get_chart_data("client-uuid", value="weight")
        print(resp.json())

asyncio.run(main())
```

## Using the CLI

```bash
# List workout programs
kahunas workouts list

# Show a specific workout program
kahunas workouts show <uuid>

# List exercises
kahunas exercises list

# Search exercises
kahunas exercises search "bench press"

# List clients
kahunas clients list

# Export client data to Excel
kahunas export client <client-uuid> --output ./exports
kahunas export all-clients --output ./exports
kahunas export exercises --output ./exports
kahunas export workouts --output ./exports

# Raw API call
kahunas api v1/workoutprogram

# Start the MCP server (stdio)
kahunas serve
```

## Using as an MCP Server

The Kahunas MCP server exposes all API endpoints as tools that AI assistants can call. It uses the **stdio** transport, which is the standard way to connect MCP servers to AI tools.

### With Claude Desktop

Add this to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS or `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "kahunas": {
      "command": "kahunas-mcp",
      "env": {
        "KAHUNAS_EMAIL": "you@example.com",
        "KAHUNAS_PASSWORD": "your-password"
      }
    }
  }
}
```

Or if installed from source with a virtualenv:

```json
{
  "mcpServers": {
    "kahunas": {
      "command": "/path/to/venv/bin/kahunas-mcp",
      "env": {
        "KAHUNAS_EMAIL": "you@example.com",
        "KAHUNAS_PASSWORD": "your-password"
      }
    }
  }
}
```

### With Claude Code (CLI)

Add to your project's `.claude/mcp.json`:

```json
{
  "mcpServers": {
    "kahunas": {
      "command": "kahunas-mcp",
      "env": {
        "KAHUNAS_EMAIL": "you@example.com",
        "KAHUNAS_PASSWORD": "your-password"
      }
    }
  }
}
```

### With ChatGPT (via MCP Bridge)

ChatGPT supports MCP servers through compatible bridges. Use any stdio-to-HTTP bridge that supports MCP:

```bash
# Example: using an MCP-to-SSE bridge
kahunas serve  # starts the MCP server on stdio
```

Then configure the bridge to proxy stdio to your ChatGPT-compatible endpoint.

### With Any MCP-Compatible AI Tool

The server speaks standard MCP over stdio. Any tool that supports MCP can connect:

```bash
# Direct stdio invocation
kahunas-mcp

# Or via Python module
python -m kahunas_client.mcp
```

### Available MCP Tools

Once connected, the AI assistant has access to these tools:

| Tool | Description |
|------|-------------|
| `login` | Authenticate with Kahunas (call first) |
| `logout` | Close the session |
| `list_workout_programs` | List all workout programs |
| `get_workout_program` | Get full workout program details |
| `assign_workout_program` | Assign a program to a client |
| `restore_workout_program` | Restore an archived program |
| `list_exercises` | Browse the exercise library |
| `search_exercises` | Search exercises by keyword |
| `list_clients` | List all coaching clients |
| `create_client` | Create a new client |
| `get_client` | View/edit/manage a client |
| `manage_diet_plan` | Manage diet plans |
| `manage_supplement_plan` | Manage supplement plans |
| `view_checkin` | View a client check-in |
| `delete_checkin` | Delete a check-in |
| `compare_checkins` | Compare check-in data over time |
| `create_habit` | Create a new habit for a client |
| `complete_habit` | Mark a habit as completed |
| `list_habits` | List habits for a client |
| `list_chat_contacts` | List chat contacts |
| `get_chat_messages` | Get chat messages with a client |
| `send_chat_message` | Send a chat message |
| `manage_package` | Manage coaching packages |
| `delete_calendar_event` | Delete a calendar event |
| `update_coach_settings` | Update coach configuration |
| `get_client_progress` | Get body measurement progress |
| `get_exercise_progress` | Get exercise strength progress |
| `get_workout_log` | Get workout log book |
| `notify_client` | Send notification to a client |
| `export_client_data` | Export all client data to Excel |
| `export_all_clients` | Export all clients to Excel |
| `export_exercises` | Export exercise library to Excel |
| `export_workout_programs` | Export workout programs to Excel |
| `api_request` | Make a raw API request |

### Example AI Conversations

Once the MCP server is connected to your AI assistant, you can ask:

> "Show me all my clients and their check-in status"

> "Export all data for John Doe to Excel files"

> "Search for squat variations in the exercise library"

> "What's the workout program 'PPL Advanced' look like?"

> "Create a new client named Jane Smith with email jane@example.com"

> "Show me John's weight progress over the last 3 months"

## Data Export

Exports are organized in a user-friendly directory structure with Excel files:

```
kahunas_exports/20260306_143022/
├── John Doe/
│   ├── profile.xlsx          # Client profile and account info
│   ├── checkins/
│   │   ├── checkins_summary.xlsx  # All check-ins overview
│   │   └── photos/           # Progress photos
│   │       ├── checkin_1_1.jpg
│   │       └── checkin_2_1.jpg
│   ├── progress/
│   │   └── body_measurements.xlsx  # Weight, body fat, measurements
│   ├── habits/
│   │   └── habit_tracking.xlsx     # Habit completion history
│   └── chat/
│       └── chat_history.xlsx       # Full chat message history
├── Jane Smith/
│   └── ...
├── workout_programs/
│   ├── PPL Advanced.xlsx     # One file per program
│   └── Upper Lower.xlsx      # Each day is a separate sheet
└── exercise_library.xlsx     # Full exercise catalog
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run linter
ruff check src/ tests/

# Format code
ruff format src/ tests/

# Run tests with coverage
pytest --cov=kahunas_client --cov-report=term-missing
```

## Architecture

```
src/kahunas_client/
├── __init__.py          # Package version
├── client.py            # Async HTTP client (httpx)
├── config.py            # Configuration (env vars, YAML, .env)
├── exceptions.py        # Custom exception hierarchy
├── models/              # Pydantic v2 models
│   ├── auth.py          # Auth credentials/session
│   ├── clients.py       # Client, CheckIn, Habit, ChatMessage
│   ├── common.py        # Pagination, ApiResponse, MediaItem
│   ├── exercises.py     # Exercise, ExerciseListData
│   └── workouts.py      # WorkoutProgram, WorkoutDay, ExerciseSet
├── mcp/                 # MCP server (FastMCP 3.x, stdio)
│   ├── server.py        # Tool definitions
│   ├── export.py        # Excel export manager
│   └── __main__.py      # Entry point
└── cli/                 # CLI (Click + Rich)
    └── main.py          # Command definitions
```

## License

MIT
