"""Confirm a real artifact swap without changing approved sandbox copy."""
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


def verify_canary(url: str, run_id: str, *, present: bool, attempts: int = 8,
                  delay: float = 5) -> bool:
    if not run_id.isascii() or not run_id.isdigit():
        raise ValueError("Run ID must be decimal")
    marker = urljoin(url.rstrip("/") + "/", "rollback-drill-canary.txt")
    for attempt in range(attempts):
        try:
            request = Request(marker + "?run=" + run_id,
                              headers={"Cache-Control": "no-cache"})
            with urlopen(request, timeout=10) as response:
                body = response.read(1024)
                if present and response.status == 200 and body == run_id.encode("ascii"):
                    return True
        except HTTPError as exc:
            code = exc.code
            exc.close()
            if not present and code == 404:
                return True
        except OSError:
            pass
        if attempt + 1 < attempts:
            time.sleep(delay)
    return False


if __name__ == "__main__":
    mode, url, run_id = sys.argv[1:]
    if mode not in {"present", "absent"}:
        raise SystemExit("Unknown drill check")
    if not verify_canary(url, run_id, present=mode == "present"):
        raise SystemExit("Rollback artifact marker check failed")
    print("Rollback marker verified: " + mode)
