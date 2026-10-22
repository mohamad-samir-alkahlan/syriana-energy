"""Dump raw ShineMonitor responses so the owner can verify the driver against the live API.

    python -m app.tools.shinemonitor_probe --user NAME --password PASS [--base URL] [--out probe.json]
                                           [--pn PN --sn SN --devcode N --devaddr N]

Logs in, lists devices, then (read-only!) fetches energy-flow, one-day paging, control fields (+ current values for
the first few) and warnings for each device, writing every raw response (tokens redacted) to JSON.
It never calls ctrlDevice. Compare the output with backend/tests/fixtures/eybond/*.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone

from app.drivers.eybond_cloud import ShineClient
from app.drivers.base import DriverError


async def probe(args: argparse.Namespace) -> dict:
    c = ShineClient(args.user, args.password, base=args.base)
    c.trace = []
    out: dict = {"base": c.base, "ts": datetime.now(timezone.utc).isoformat(), "trace": c.trace, "errors": []}

    async def safe(name: str, **kw):
        try:
            return await c.call(name, **kw)
        except DriverError as e:
            out["errors"].append({"action": name, "error": e.message, "err": e.err})
            return None

    try:
        await c.login()
    except DriverError as e:
        out["errors"].append({"action": "authSource", "error": e.message, "err": e.err})
        return out
    devices = []
    if args.pn and args.sn:
        devices = [{"pn": args.pn, "sn": args.sn, "devcode": args.devcode, "devaddr": args.devaddr}]
    else:
        dat = await safe("webQueryDeviceEs", page=0, pagesize=50)
        devices = (dat or {}).get("device", []) or []
    today = datetime.now().date().isoformat()
    for d in devices[: args.max_devices]:
        pn, sn, dc, da = (str(d.get(k, "")) for k in ("pn", "sn", "devcode", "devaddr"))
        await safe("webQueryDeviceEnergyFlowEs", pn=pn, sn=sn, devaddr=da, devcode=dc)
        page = await safe("queryDeviceDataOneDayPaging", pn=pn, devcode=dc, sn=sn, devaddr=da, page=0, pagesize=1, date=args.date or today)
        total = int((page or {}).get("total") or 0)
        if total > 1:
            await safe("queryDeviceDataOneDayPaging", pn=pn, devcode=dc, sn=sn, devaddr=da, page=total - 1, pagesize=1, date=args.date or today)
        fields = await safe("webQueryDeviceCtrlField", pn=pn, sn=sn, devcode=dc, devaddr=da)
        for f in ((fields or {}).get("field") or [])[: args.max_fields]:
            await safe("queryDeviceCtrlValue", pn=pn, sn=sn, devcode=dc, devaddr=da, id=f.get("id"))
        await safe("queryDeviceWarning", pn=pn, devcode=dc, devaddr=da, sn=sn, page=0, pagesize=10, mode="strict")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--base", default=None, help="default: $SHINEMONITOR_BASE or http://android.shinemonitor.com/public/")
    ap.add_argument("--out", default="-", help="output file (default stdout)")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD for the one-day paging call (default: today)")
    ap.add_argument("--pn"), ap.add_argument("--sn")
    ap.add_argument("--devcode", default="")
    ap.add_argument("--devaddr", default="")
    ap.add_argument("--max-devices", type=int, default=3)
    ap.add_argument("--max-fields", type=int, default=60)
    args = ap.parse_args()
    result = asyncio.run(probe(args))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out == "-":
        print(text)
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {args.out} ({len(result['trace'])} calls, {len(result['errors'])} errors)", file=sys.stderr)
    return 1 if result["errors"] and not result["trace"] else 0


if __name__ == "__main__":
    sys.exit(main())
