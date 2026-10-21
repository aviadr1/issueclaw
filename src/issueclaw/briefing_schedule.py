"""Plan scheduled exceptions and early manual delivery before collecting evidence.

This entry point uses only the standard library so the reusable workflow can skip
a scheduled exception without installing reporting or model dependencies.
"""

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING or __package__:
    from .briefing_config import load_config
else:
    from briefing_config import load_config


def plan(config, now, event, *, early=False):
    if early and event != "workflow_dispatch":
        raise ValueError("An early briefing requires a manual workflow dispatch")
    date = now.astimezone(ZoneInfo(config["timezone"])).date().isoformat()
    excluded = event == "schedule" and date in config.get("skip_scheduled_dates", [])
    return {
        "enabled": not excluded,
        "cutoff": now.astimezone(timezone.utc).isoformat() if early else "",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--early", action="store_true")
    args = parser.parse_args()
    result = plan(
        load_config(args.config),
        datetime.now(timezone.utc),
        args.event,
        early=args.early,
    )
    print(f"enabled={str(result['enabled']).lower()}")
    print(f"cutoff={result['cutoff']}")


if __name__ == "__main__":
    main()
