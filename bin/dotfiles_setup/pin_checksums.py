"""Re-records the SHA-256 digests in packages/checksums.txt from what each URL serves now.

Re-recording trusts whatever the URL serves today, so review the diff before committing it."""
from __future__ import annotations

import argparse
import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from dotfiles_setup.checksums import FILE_NAME
from dotfiles_setup.tooling import fetch_bytes_https

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "packages" / FILE_NAME
_LINE = re.compile(r"^\s*(?P<digest>[0-9a-f]{64})\s+(?P<url>\S+)")

Fetch = Callable[[str], bytes]


@dataclass(frozen=True)
class Pin:
    url: str
    recorded: str
    actual: str | None
    error: str = ""

    @property
    def stale(self) -> bool:
        return self.actual is not None and self.actual != self.recorded


def _measure(url: str, recorded: str, fetch: Fetch) -> Pin:
    try:
        return Pin(url, recorded, hashlib.sha256(fetch(url)).hexdigest())
    except (OSError, ValueError) as error:
        return Pin(url, recorded, None, str(error))


def _wanted(url: str, filters: Sequence[str]) -> bool:
    return not filters or any(part in url for part in filters)


def _malformed(line: str, filters: Sequence[str]) -> Pin | None:
    """The loader ignores such a line, so the installer would later refuse its URL as having no digest."""
    entry = line.partition("#")[0].strip()
    if not entry or not _wanted(entry, filters):
        return None
    return Pin(entry, "", None, "not a '<sha256>  <url>' entry")


def _pin_line(line: str, filters: Sequence[str], fetch: Fetch) -> tuple[str, Pin | None]:
    match = _LINE.match(line)
    if match is None:
        return line, _malformed(line, filters)
    if not _wanted(match["url"], filters):
        return line, None
    pin = _measure(match["url"], match["digest"], fetch)
    return (line.replace(pin.recorded, pin.actual, 1) if pin.stale and pin.actual else line), pin


def pin_text(text: str, filters: Sequence[str], fetch: Fetch) -> tuple[str, list[Pin]]:
    pins: list[Pin] = []
    lines: list[str] = []
    for line in text.splitlines(keepends=True):
        new_line, pin = _pin_line(line, filters, fetch)
        lines.append(new_line)
        if pin is not None:
            pins.append(pin)
    return "".join(lines), pins


def _report(pins: Sequence[Pin]) -> None:
    for pin in pins:
        if pin.error:
            print(f"ERROR  {pin.url}: {pin.error}")
        elif pin.stale:
            print(f"STALE  {pin.url}\n         recorded {pin.recorded}\n         serves   {pin.actual}")
        else:
            print(f"ok     {pin.url}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pin", description="Re-record stale digests in packages/checksums.txt.")
    parser.add_argument("filter", nargs="*", help="only URLs containing one of these substrings")
    parser.add_argument("--check", action="store_true", help="report only; exit 1 on a stale digest or a failed download")
    return parser


def main(argv: Sequence[str] | None = None, path: Path = DEFAULT_PATH, fetch: Fetch = fetch_bytes_https) -> int:
    args = _parser().parse_args(argv)
    new_text, pins = pin_text(path.read_text(), args.filter, fetch)
    if not pins:
        print("No URL in the checksums file matched.")
        return 1
    _report(pins)
    stale, failed = [p for p in pins if p.stale], [p for p in pins if p.error]
    if not args.check and stale:
        with path.open("w") as handle:
            handle.write(new_text)
        print(f"Re-recorded {len(stale)} digest(s). Review `git diff {path}`: this trusts what the URLs serve now.")
    return 1 if failed or (args.check and stale) else 0
