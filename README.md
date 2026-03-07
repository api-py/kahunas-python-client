# Kahunas Python Client

Python client library, CLI, and MCP server for the [Kahunas](https://kahunas.io) fitness coaching platform.

## Features

- **Python Client** — Async HTTP client (`httpx`) with Pydantic v2 models, automatic token refresh, retry logic, and connection resilience
- **MCP Server** — Stdio-based [Model Context Protocol](https://modelcontextprotocol.io/) server with **compact JSON payloads** optimised for LLM context windows
- **CLI** — Command-line interface with rich terminal output for managing clients, workouts, exercises, and exports
- **Charts** — Generate PNG progress charts (body weight, body fat, steps, measurements) using `matplotlib`
- **WhatsApp Integration** — Send messages and attachments to clients via WhatsApp Business Cloud API with automatic phone number normalisation (UK +44 default)
- **Data Export** — Export all client data (profiles, check-ins, progress photos, workouts, habits, chat history) to Excel files
- **Auto Re-authentication** — Tokens are automatically refreshed when they expire

## Requirements

- Python 3.12+
- A Kahunas coaching account (email & password or auth token)

## Installation

```bash
pip install kahunas-client
```

Or install from source:

```bash
git clone https://github.com/api-py/kahunas-python-client.git
cd kahunas-python-client
pip install -e ".[dev]"
```

## Configuration

The client supports multiple ways to provide credentials, in order of priority:

### 1. Environment Variables

```bash
export KAHUNAS_EMAIL="you@example.com"
export KAHUNAS_PASSWORD="your-password"

# Optional: WhatsApp Business API
export WHATSAPP_TOKEN="your-meta-cloud-api-token"
export WHATSAPP_PHONE_NUMBER_ID="your-whatsapp-phone-number-id"
export WHATSAPP_DEFAULT_COUNTRY_CODE="44"  # UK default
```

### 2. `.env` File

```env
KAHUNAS_EMAIL=you@example.com
KAHUNAS_PASSWORD=your-password
WHATSAPP_TOKEN=your-meta-cloud-api-token
WHATSAPP_PHONE_NUMBER_ID=your-whatsapp-phone-number-id
```

### 3. YAML Config File

```yaml
# config.yaml
email: you@example.com
password: your-password
timeout: 60.0
whatsapp_token: your-meta-cloud-api-token
whatsapp_phone_number_id: your-whatsapp-phone-number-id
whatsapp_default_country_code: "44"
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
from kahunas_client import KahunasClient, KahunasConfig

async def main():
    config = KahunasConfig(email="you@example.com", password="your-password")

    async with KahunasClient(config) as client:
        # List workout programs
        programs = await client.list_workout_programs()
        for p in programs.workout_plan:
            print(f"{p.title} — {p.days} days")

        # Search exercises
        exercises = await client.search_exercises("squat")
        for ex in exercises:
            print(f"{ex.exercise_name} ({ex.exercise_type})")

asyncio.run(main())
```

### Generating Progress Charts

```python
from kahunas_client.charts import generate_chart

# Data points from the Kahunas API (or manual entry)
data = [
    {"date": "2024-01-01", "value": 85.0},
    {"date": "2024-02-01", "value": 83.5},
    {"date": "2024-03-01", "value": 82.0},
]

# Generate a PNG chart
png_bytes = generate_chart(
    data_points=data,
    metric="weight",          # weight, bodyfat, steps, chest, waist, etc.
    time_range="quarter",     # week, month, quarter, year, all
    client_name="John Doe",
    output_path="/tmp/weight_chart.png",
)
```

### WhatsApp Business API

```python
from kahunas_client.whatsapp import WhatsAppClient, WhatsAppConfig, normalise_phone

# Normalise phone numbers (resilient to format variations)
normalise_phone("07700 900 123")     # -> "447700900123"
normalise_phone("+44 7700 900123")   # -> "447700900123"
normalise_phone("0044 7700 900123")  # -> "447700900123"

# Send messages
config = WhatsAppConfig(
    access_token="your-meta-token",
    phone_number_id="your-phone-number-id",
)
async with WhatsAppClient(config) as wa:
    await wa.send_text("447700900123", "Hi! Your check-in looks great.")
    await wa.send_image("447700900123", "https://example.com/chart.png", "Weight progress")
    await wa.send_document("447700900123", "https://example.com/report.xlsx", "report.xlsx")
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

The Kahunas MCP server exposes all API endpoints as tools that AI assistants can call. It uses the **stdio** transport.

### With Claude Desktop

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "kahunas": {
      "command": "kahunas-mcp",
      "env": {
        "KAHUNAS_EMAIL": "you@example.com",
        "KAHUNAS_PASSWORD": "your-password",
        "WHATSAPP_TOKEN": "your-meta-token",
        "WHATSAPP_PHONE_NUMBER_ID": "your-phone-id"
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

### Available MCP Tools

Once connected, the AI assistant has access to these tools (sorted alphabetically):

| Tool | Description |
|------|-------------|
| `api_request` | Make a raw authenticated API request |
| `assign_workout_program` | Assign a workout program to a client |
| `compare_checkins` | Compare check-in data over time |
| `complete_habit` | Mark a habit as completed |
| `create_client` | Create a new coaching client |
| `create_habit` | Create a new habit for a client |
| `delete_calendar_event` | Delete a calendar event |
| `delete_checkin` | Delete a client check-in |
| `export_all_clients` | Export all clients data to Excel |
| `export_client_data` | Export a single client's data to Excel |
| `export_exercises` | Export exercise library to Excel |
| `export_workout_programs` | Export workout programs to Excel |
| `generate_progress_chart` | Generate a PNG chart for weight, body fat, steps, etc. |
| `get_chat_messages` | Get chat messages with a client |
| `get_client` | View, edit, or manage a client |
| `get_client_progress` | Get body measurement progress data |
| `get_exercise_progress` | Get exercise strength/volume progress |
| `get_workout_log` | Get workout log book for an exercise |
| `list_chat_contacts` | List clients available for chat |
| `list_clients` | List all coaching clients |
| `list_exercises` | Browse the exercise library |
| `list_habits` | List habits for a client |
| `list_workout_programs` | List all workout programs |
| `login` | Authenticate with Kahunas (call first) |
| `logout` | Close the Kahunas session |
| `manage_diet_plan` | Manage diet plans (list, create, update, delete) |
| `manage_package` | Manage coaching packages |
| `manage_supplement_plan` | Manage supplement plans |
| `notify_client` | Send a notification to a client |
| `restore_workout_program` | Restore an archived workout program |
| `search_exercises` | Search exercises by keyword |
| `send_chat_message` | Send a Kahunas chat message to a client |
| `update_coach_settings` | Update coach configuration settings |
| `view_checkin` | View a client check-in |
| `whatsapp_send_image` | Send an image via WhatsApp |
| `whatsapp_send_message` | Send a text message via WhatsApp |
| `whatsapp_validate_clients` | Check which clients have valid WhatsApp numbers |

### Example AI Conversations

> "Show me all my clients and their check-in status"

> "Generate a weight chart for John Doe over the last 3 months"

> "Send John a WhatsApp message: Great progress this week!"

> "Which of my clients have valid WhatsApp numbers?"

> "Export all data for Jane Smith to Excel"

## WhatsApp Business Integration

The WhatsApp integration uses the **Meta Cloud API** (WhatsApp Business Platform). This is the official, well-established API for programmatic WhatsApp messaging.

### Setup

1. Create a Meta Business account at [business.facebook.com](https://business.facebook.com)
2. Set up a WhatsApp Business App in the [Meta Developer Portal](https://developers.facebook.com)
3. Generate a permanent access token
4. Note your Phone Number ID from the WhatsApp settings

### Phone Number Normalisation

The client automatically normalises phone numbers to E.164 format. This is resilient to common UK and international formats:

| Input | Normalised |
|-------|-----------|
| `07700 900 123` | `447700900123` |
| `+44 7700 900123` | `447700900123` |
| `0044 7700 900 123` | `447700900123` |
| `7700900123` | `447700900123` |
| `+1 (555) 123-4567` | `15551234567` |

The default country code is `44` (UK) but can be configured via `WHATSAPP_DEFAULT_COUNTRY_CODE`.

## Charts

Progress charts are generated using **matplotlib** (industry-standard Python plotting library) and saved as PNG images.

### Supported Metrics

| Metric | Label | Unit |
|--------|-------|------|
| `weight` | Body Weight | kg |
| `bodyfat` | Body Fat | % |
| `steps` | Steps | steps |
| `chest` | Chest | cm |
| `waist` | Waist | cm |
| `hips` | Hips | cm |
| `arms` | Arms | cm |
| `thighs` | Thighs | cm |

### Time Ranges

`week` · `month` · `quarter` · `year` · `all`

Charts include trend lines, min/max/average stats, and change annotations.

## Data Export

Exports are organized in a user-friendly directory structure with Excel files:

```
kahunas_exports/20260306_143022/
├── John Doe/
│   ├── profile.xlsx
│   ├── checkins/
│   │   ├── checkins_summary.xlsx
│   │   └── photos/
│   ├── progress/
│   │   └── body_measurements.xlsx
│   ├── habits/
│   │   └── habit_tracking.xlsx
│   └── chat/
│       └── chat_history.xlsx
├── workout_programs/
│   ├── PPL Advanced.xlsx
│   └── Upper Lower.xlsx
└── exercise_library.xlsx
```

## Architecture

```
src/kahunas_client/
├── __init__.py          # Package exports
├── charts.py            # Chart generation (matplotlib)
├── client.py            # Async HTTP client (httpx + tenacity retries)
├── config.py            # Configuration (env vars, YAML, .env)
├── exceptions.py        # Custom exception hierarchy
├── whatsapp.py          # WhatsApp Business API client
├── models/              # Pydantic v2 models
│   ├── auth.py          # Auth credentials/session
│   ├── clients.py       # Client, CheckIn, Habit, ChatMessage
│   ├── common.py        # Pagination, ApiResponse, MediaItem
│   ├── exercises.py     # Exercise, ExerciseListData
│   └── workouts.py      # WorkoutProgram, WorkoutDay, ExerciseSet
├── mcp/                 # MCP server (FastMCP 3.x, stdio)
│   ├── server.py        # Tool definitions (compact JSON payloads)
│   ├── export.py        # Excel export manager
│   └── __main__.py      # Entry point
└── cli/                 # CLI (Click + Rich)
    └── main.py          # Command definitions
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests (135 tests)
pytest tests/ -v

# Run linter
ruff check src/ tests/

# Format code
ruff format src/ tests/

# Run functional tests (requires auth token)
python tests/functional_test.py
```

## License

MIT
