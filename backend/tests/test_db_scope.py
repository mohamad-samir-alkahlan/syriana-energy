"""Guard: every DB session dependency must commit BEFORE the response is sent (scope="function").

With the default "request" scope FastAPI runs the commit after the response went out, so a client that reads right
after a write could see stale data when the commit waits on a row lock held by the worker (found in the E2E suite as
a flaky "rename device" test)."""
import re
from pathlib import Path


def test_get_db_always_function_scoped():
    bad = []
    for f in (Path(__file__).resolve().parents[1] / "app").rglob("*.py"):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if re.search(r"Depends\(get_db\)", line):
                bad.append(f"{f.name}:{i}")
    assert not bad, f"use Depends(get_db, scope='function'): {bad}"
