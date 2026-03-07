# Kahunas Python Client

Python client library, CLI, and MCP server for the [Kahunas](https://kahunas.io) fitness coaching platform.

## Features

- **Python Client** — Async HTTP client (`httpx`) with Pydantic v2 models, automatic token refresh, retry logic, and connection resilience
- **MCP Server** — Stdio-based [Model Context Protocol](https://modelcontextprotocol.io/) server with **57 tools** and compact JSON payloads optimised for LLM context windows
- **CLI** — Command-line interface with rich terminal output for managing clients, workouts, exercises, and exports
- **Charts** — Generate PNG progress charts (body weight, body fat, steps, measurements) using `matplotlib`
- **Calendar Sync** — Sync Kahunas appointments with Google Calendar or Apple Calendar (iCal), with preview/add/remove/sync/trust modes for LLM-driven orchestration
- **Check-in History** — Tabular check-in summaries with body measurements, lifestyle ratings, and trend analysis
- **Local Metrics Store** — SQLite-backed timeseries database for offline chart generation and metric queries
- **WhatsApp Integration** — Send messages and attachments to clients via WhatsApp Business Cloud API with automatic phone number normalisation (UK +44 default)
- **Data Export** — Export all client data (profiles, check-ins, progress photos, workouts, habits, chat history) to Excel files
- **Configurable Units** — Weight (kg/lbs), height (cm/inches), glucose, food, and water units matching the Kahunas coach configuration page
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

# Optional: Calendar Sync
export KAHUNAS_CALENDAR_PREFIX="Workout"       # Event title prefix
export KAHUNAS_DEFAULT_GYM="PureGym London"    # Default location
export KAHUNAS_GYM_LIST="PureGym,The Gym,Home" # Available gyms
export KAHUNAS_CALENDAR_DEFAULT_DURATION="60"  # Minutes

# Optional: Measurement Units (match Kahunas coach/configuration)
export KAHUNAS_WEIGHT_UNIT="kg"       # kg or lbs
export KAHUNAS_HEIGHT_UNIT="cm"       # cm or inches
export KAHUNAS_GLUCOSE_UNIT="mmol_l"  # mmol_l or mg_dl
export KAHUNAS_FOOD_UNIT="grams"      # grams, ounces, qty, cups, oz, ml, tsp
export KAHUNAS_WATER_UNIT="ml"        # ml, l, or oz

# Optional: Timezone
export KAHUNAS_TIMEZONE="Europe/London"  # IANA timezone
```

### 2. `.env` File

```env
KAHUNAS_EMAIL=you@example.com
KAHUNAS_PASSWORD=your-password
WHATSAPP_TOKEN=your-meta-cloud-api-token
WHATSAPP_PHONE_NUMBER_ID=your-whatsapp-phone-number-id
KAHUNAS_WEIGHT_UNIT=lbs
KAHUNAS_HEIGHT_UNIT=inches
KAHUNAS_TIMEZONE=America/New_York
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
calendar_prefix: "PT"
default_gym: "PureGym"
weight_unit: "lbs"
height_unit: "inches"
timezone: "Europe/London"
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
        "WHATSAPP_PHONE_NUMBER_ID": "your-phone-id",
        "KAHUNAS_WEIGHT_UNIT": "lbs",
        "KAHUNAS_HEIGHT_UNIT": "inches"
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

Once connected, the AI assistant has access to **57 tools** (sorted alphabetically):

| Tool | Description |
|------|-------------|
| `api_request` | Make a raw authenticated API request |
| `appointment_overview` | Get a comprehensive overview of appointments across time windows (upcoming + historical counts) |
| `assign_workout_program` | Assign a workout program to a client |
| `checkin_summary` | Get a tabular check-in history summary with body measurements, lifestyle ratings, and trends |
| `client_appointment_counts` | Get appointment counts for a specific client across time windows |
| `compare_checkins` | Compare check-in data over time |
| `complete_habit` | Mark a habit as completed |
| `create_client` | Create a new coaching client |
| `create_habit` | Create a new habit for a client |
| `delete_calendar_event` | Delete a calendar event |
| `delete_checkin` | Delete a client check-in |
| `discover_all_exercises` | Discover and list ALL exercises in the Kahunas exercise library |
| `discover_diet_plans` | Discover all diet plans available in Kahunas |
| `discover_supplement_plans` | Discover all supplement plans available in Kahunas |
| `export_all_clients` | Export all clients data to Excel |
| `export_client_data` | Export a single client's data to Excel |
| `export_exercises` | Export exercise library to Excel |
| `export_workout_programs` | Export workout programs to Excel |
| `find_client_appointments` | Find all calendar appointments for a specific client by UUID or name |
| `format_appointments_gcal` | Format Kahunas appointments as Google Calendar event objects |
| `generate_chart_from_store` | Generate a PNG chart from locally stored metric data (no API call needed) |
| `generate_progress_chart` | Generate a PNG chart for weight, body fat, steps, etc. |
| `get_chat_messages` | Get chat messages with a client |
| `get_client` | View, edit, or manage a client |
| `get_client_progress` | Get body measurement progress data |
| `get_exercise_progress` | Get exercise strength/volume progress |
| `get_measurement_settings` | Get configured measurement unit settings (weight, height, glucose, food, water) |
| `get_workout_log` | Get workout log book for an exercise |
| `get_workout_program` | Get full workout program details including all days and exercises |
| `list_appointments` | List Kahunas appointments filtered by time range |
| `list_chat_contacts` | List clients available for chat |
| `list_clients` | List all coaching clients |
| `list_exercises` | Browse the exercise library |
| `list_gyms` | List configured gyms/locations for calendar appointments |
| `list_habits` | List habits for a client |
| `list_stored_clients` | List all clients with locally stored metric data |
| `list_workout_programs` | List all workout programs |
| `login` | Authenticate with Kahunas (call first) |
| `logout` | Close the Kahunas session |
| `manage_diet_plan` | Manage diet plans (list, create, update, delete) |
| `manage_package` | Manage coaching packages |
| `manage_supplement_plan` | Manage supplement plans |
| `notify_client` | Send a notification to a client |
| `query_client_metrics` | Query stored metric data from the local timeseries database |
| `remove_client` | Remove a client from Kahunas and/or their calendar appointments |
| `restore_workout_program` | Restore an archived workout program |
| `search_exercises` | Search exercises by keyword |
| `send_chat_message` | Send a Kahunas chat message to a client |
| `store_client_metrics` | Store client metric data points in the local timeseries database |
| `sync_appointments_ics` | Generate an iCal (.ics) file for Apple Calendar from Kahunas appointments |
| `sync_calendar` | Sync Kahunas appointments with Google Calendar or Apple Calendar |
| `sync_client_metrics` | Fetch client metrics from Kahunas API and store locally |
| `update_coach_settings` | Update coach configuration settings |
| `view_checkin` | View a client check-in |
| `whatsapp_send_image` | Send an image via WhatsApp |
| `whatsapp_send_message` | Send a text message via WhatsApp |
| `whatsapp_validate_clients` | Check which clients have valid WhatsApp numbers |

### Calendar Sync

The calendar sync system supports both **Google Calendar** and **Apple Calendar** with LLM-driven orchestration:

| Mode | Description |
|------|-------------|
| `preview` | Show what would be added/removed/updated (default, safe) |
| `add` | Add new Kahunas appointments not yet in calendar |
| `remove` | Remove calendar events for deleted Kahunas appointments |
| `sync` | Full two-way sync: add new + remove deleted |
| `trust` | Trust all: sync everything without individual confirmation |

For **Google Calendar**, the `sync_calendar` and `format_appointments_gcal` tools return event objects directly compatible with the `gcal_create_event` MCP tool, enabling AI assistants to create events on behalf of the user.

For **Apple Calendar**, the `sync_appointments_ics` tool generates `.ics` files that can be imported into Apple Calendar, Outlook, or any iCal-compatible app.

### Check-in History

The `checkin_summary` tool replicates the Check In History table from the Kahunas coach dashboard:

- **Body measurements**: Weight, Waist, Hips, Biceps, Thighs
- **Lifestyle ratings (1-10)**: Sleep, Nutrition Adherence, Workout Rating, Stress, Energy, Mood/Wellbeing
- **Water intake**: Litres
- **Trend analysis**: Change between check-ins with direction indicators
- **Configurable units**: Respects your weight (kg/lbs) and measurement (cm/inches) settings

### Local Metrics Store

Client progress data can be cached locally in a SQLite database (`~/.kahunas/metrics.db`) for offline chart generation:

```
store_client_metrics  →  Save data points locally
query_client_metrics  →  Query stored data by date range
sync_client_metrics   →  Fetch from API and store locally
generate_chart_from_store  →  Generate charts without API calls
list_stored_clients   →  See which clients have cached data
```

### Example AI Conversations

> "Show me all my clients and their check-in status"

> "Show me Bruce Wayne's check-in history with his measurements and lifestyle ratings"

> "Generate a weight chart for John Doe over the last 3 months"

> "What appointments do I have for the rest of this week?"

> "How many sessions has Bruce Wayne had in the last 3 months?"

> "Preview my calendar sync for the next month, then add the new appointments to Google Calendar"

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
| `weight` | Body Weight | kg / lbs |
| `bodyfat` | Body Fat | % |
| `steps` | Steps | steps |
| `chest` | Chest | cm / inches |
| `waist` | Waist | cm / inches |
| `hips` | Hips | cm / inches |
| `arms` | Arms | cm / inches |
| `thighs` | Thighs | cm / inches |

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
├── calendar_sync.py     # Calendar sync (iCal, Google Calendar formatting)
├── charts.py            # Chart generation (matplotlib)
├── checkin_history.py   # Check-in history parsing, trends, appointment overview
├── client.py            # Async HTTP client (httpx + tenacity retries)
├── config.py            # Configuration (env vars, YAML, .env, units, timezone)
├── exceptions.py        # Custom exception hierarchy
├── metrics_store.py     # Local SQLite timeseries database for progress data
├── whatsapp.py          # WhatsApp Business API client
├── models/              # Pydantic v2 models
│   ├── auth.py          # Auth credentials/session
│   ├── clients.py       # Client, CheckIn, Habit, ChatMessage
│   ├── common.py        # Pagination, ApiResponse, MediaItem
│   ├── exercises.py     # Exercise, ExerciseListData
│   └── workouts.py      # WorkoutProgram, WorkoutDay, ExerciseSet
├── mcp/                 # MCP server (FastMCP 3.x, stdio)
│   ├── server.py        # 57 tool definitions (compact JSON payloads)
│   ├── export.py        # Excel export manager
│   └── __main__.py      # Entry point
└── cli/                 # CLI (Click + Rich)
    └── main.py          # Command definitions
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests (394 tests)
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
