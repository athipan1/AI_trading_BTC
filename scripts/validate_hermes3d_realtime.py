from __future__ import annotations

import asyncio
import json

from app.integrations.hermes3d.validation import validate_realtime_pipeline


def main() -> None:
    result = asyncio.run(validate_realtime_pipeline())
    print(json.dumps({"event": "HERMES3D_E2E_VALIDATION", **result.as_dict()}, indent=2))
    if not result.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
