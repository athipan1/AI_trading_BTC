from __future__ import annotations

import json
import os

from app.notifications.line_messaging import LineMessagingNotifier


def main() -> None:
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    target_id = os.environ.get("LINE_TARGET_ID", "")
    notifier = LineMessagingNotifier(token, target_id)
    result = notifier.send_text("Trading BTC\n✅ LINE Messaging API เชื่อมต่อสำเร็จ")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
