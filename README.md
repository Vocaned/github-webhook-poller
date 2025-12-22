# GitHub to Discord Webhook Poller

This script polls the GitHub Events API and forwards the events to a Discord Webhook.

## Prerequisites

- Python 3.11 or higher
- A GitHub Personal Access Token (for higher API rate limits)
- A Discord Webhook URL

## Usage

1. **Clone the repository:**
   ```bash
   git clone https://github.com/vocaned/webhook.git
   cd webhook
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Edit `config.toml`:**
   Copy the example configuration file to `config.toml`.
   ```bash
   cp config.example.toml config.toml
   ```

   Edit it to contain the following details:

   - `EVENT_API`: The GitHub API endpoint to poll.
     - For a user's activity: `https://api.github.com/users/USERNAME/received_events` (events seen by the user) or `https://api.github.com/users/USERNAME/events` (events performed by the user).
     - For an organization: `https://api.github.com/orgs/ORG/events`.
   - `POLL_INTERVAL`: Time in seconds between checks. May be overridden to respects GitHub's `X-Poll-Interval` header.
   - `GH_TOKEN`: A GitHub Personal Access Token. Required to avoid strict ratelimits, and/or to access private repositories if configured to.
   - `DISCORD_WEBHOOK`: The URL of the Discord Webhook where events will be sent.
   - `REPO_BLACKLIST`: A list of repository full names (e.g., `["owner/repo"]`) to ignore.
   - `EVENT_BLACKLIST`: A list of event types to ignore (e.g., `["WatchEvent", "ForkEvent"]`).
   - `USER_WHITELIST`: A list of usernames. If set, only events triggered by these users will be forwarded.

4. **Run the module:**
   ```bash
   python -m webhook
   ```
