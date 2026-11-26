#!/usr/bin/env python3
"""Front-page publisher for ``news-image-20261126`` on make.fun.

Competition: "Sum up 26 November's world news in one image"
(https://make.fun/bounty/news-image-20261126, $100 prize pool,
deadline 2026-11-28T00:00:00Z).

The image in this repository is a newspaper front page headed
"THE WORLD TODAY, Thursday, November 26, 2026".  It sums up the
day's world news in one 1024x1024 picture:

* Pakistan's first astronaut, Muhammad Zeeshan Ali, flies aboard
  China's Shenzhou-24 and becomes the first foreign astronaut to
  board the Tiangong space station.
* North Korea expels Switzerland's envoy, Sylvain Astier, giving
  him 48 hours to leave and closing the Swiss office over sanctions.
* The Saudi-led coalition strikes Yemen's port city of Hodeida;
  the Houthis vow revenge on Jeddah and other Red Sea ports.
* All 20 hostages are freed in Cartagena after Colombian forces
  storm an Exito supermarket following a 17-hour siege.
* Australia and Solomon Islands sign a landmark Pacific pact:
  Canberra becomes the primary security partner, pledging
  A$740 million over a decade, with no foreign military bases.
* Leaked Rosstat figures analysed by the BBC put Russian war
  dead in Ukraine at at least 490,334.
* Shanghai party chief Chen Jining, a Politburo member, is
  investigated for graft -- the fourth top leader to fall since 2025.
* The United States proposes new tariffs on 14 trading partners,
  with China facing the highest rate.

What this program does
----------------------
It checks the bundled ``entry.png`` thoroughly and then publishes
an exact byte-for-byte copy of it to ``/output/entry.png``.  The
checks are: PNG magic bytes, IHDR dimensions of 1024x1024, the
IHDR CRC-32, and the 1 MiB size cap.  The copy is confirmed with
SHA-256, and a determinism self-check proves that writing the
same bytes twice gives the same hash.  Python 3.13 standard
library only; nothing is downloaded and no network is used.

Usage
-----
    python3 main.py                # publish entry.png to /output/
    python3 main.py --verify-only  # check only, write nothing
    python3 main.py --output DIR   # publish into another directory

Exit code 0 means success; any failure exits 1 with a loud
error on stderr and no output file written.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys
import tempfile
import zlib

# Competition limits for the submitted image.
CANVAS_WIDTH = 1024
CANVAS_HEIGHT = 1024
SIZE_LIMIT = 1024 * 1024  # 1 MiB, the largest allowed file

MAGIC_BYTES = b"\x89PNG\r\n\x1a\n"
FILE_NAME = "entry.png"


def report_error(message: str) -> int:
    """Print a loud error to stderr and return the failure code."""
    print(f"error: {message}", file=sys.stderr)
    return 1


def locate_image() -> str:
    """Return the absolute path of entry.png beside this script."""
    folder = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(folder, FILE_NAME)


def load_image_bytes(path: str) -> bytes:
    """Read the image file, failing loudly when it is absent."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"entry image not found: {path}")
    with open(path, "rb") as stream:
        return stream.read()


def digest_bytes(payload: bytes) -> str:
    """Return the SHA-256 hex digest of a byte string."""
    return hashlib.sha256(payload).hexdigest()


def enforce_size_limit(payload: bytes, path: str) -> None:
    """Reject the image when it is larger than the 1 MiB cap."""
    if len(payload) > SIZE_LIMIT:
        raise ValueError(
            f"{path} is {len(payload)} bytes, over the "
            f"{SIZE_LIMIT} byte limit"
        )


def decode_header(payload: bytes) -> tuple[int, int]:
    """Read width and height from the PNG signature and IHDR chunk.

    A PNG starts with 8 magic bytes, then its first chunk: a
    4-byte big-endian length, the 4-byte type "IHDR", and 13 bytes
    of data whose first 8 bytes are width and height, each a
    big-endian 32-bit integer.
    """
    if len(payload) < 8 or payload[:8] != MAGIC_BYTES:
        raise ValueError("not a PNG file: bad signature")
    if len(payload) < 8 + 8 + 13:
        raise ValueError("truncated PNG: IHDR chunk missing")
    length = struct.unpack(">I", payload[8:12])[0]
    kind = payload[12:16]
    if kind != b"IHDR":
        raise ValueError("first PNG chunk is not IHDR")
    if length != 13:
        raise ValueError(f"IHDR length is {length}, expected 13")
    width, height = struct.unpack(">II", payload[16:24])
    return width, height


def validate_ihdr_checksum(payload: bytes) -> None:
    """Check the CRC-32 stored after the IHDR chunk's data.

    A chunk CRC covers its type (4 bytes) plus its data.  IHDR
    data runs from offset 16 to 29, so the stored CRC is at
    bytes 29..33.  A mismatch means the header cannot be trusted.
    """
    if len(payload) < 33:
        raise ValueError("truncated PNG: IHDR CRC missing")
    chunk_type = payload[12:16]
    chunk_data = payload[16:29]
    stored = struct.unpack(">I", payload[29:33])[0]
    computed = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
    if stored != computed:
        raise ValueError(
            f"IHDR CRC mismatch: stored {stored:#010x}, "
            f"computed {computed:#010x}"
        )


def assert_canvas_size(width: int, height: int) -> None:
    """The front page must be exactly 1024 by 1024 pixels."""
    if (width, height) != (CANVAS_WIDTH, CANVAS_HEIGHT):
        raise ValueError(
            f"image is {width}x{height}, expected "
            f"{CANVAS_WIDTH}x{CANVAS_HEIGHT}"
        )


def walk_chunks(payload: bytes) -> None:
    """Walk every PNG chunk through to the IEND chunk.

    Each chunk is a 4-byte length, a 4-byte type, that many data
    bytes, and a 4-byte CRC.  Walking them proves the file is a
    whole image -- not a header with the data cut off -- and that
    it ends with IEND.  A chunk that runs past the end of the
    file, or a file with no IEND, is rejected.
    """
    offset = 8
    saw_iend = False
    while offset + 8 <= len(payload):
        length = struct.unpack(">I", payload[offset:offset + 4])[0]
        kind = payload[offset + 4:offset + 8]
        end = offset + 8 + length + 4
        if end > len(payload):
            raise ValueError(
                f"truncated PNG: {kind.decode('latin-1')} chunk "
                f"runs past the end of the file"
            )
        if kind == b"IEND":
            saw_iend = True
            if end != len(payload):
                raise ValueError("trailing bytes after IEND chunk")
            break
        offset = end
    if not saw_iend:
        raise ValueError("truncated PNG: no IEND chunk found")


def inspect_image(payload: bytes, path: str) -> tuple[int, int, str]:
    """Run every check on the image; return (width, height, sha256)."""
    enforce_size_limit(payload, path)
    width, height = decode_header(payload)
    validate_ihdr_checksum(payload)
    assert_canvas_size(width, height)
    walk_chunks(payload)
    return width, height, digest_bytes(payload)


def duplicate_twice(payload: bytes, expected: str) -> None:
    """Determinism self-check: two fresh copies must hash the same.

    Writes the image bytes to two temporary files and confirms
    both match the source hash.  If writing ever produced
    different bytes, the publish step below could not be trusted.
    """
    seen: list[str] = []
    with tempfile.TemporaryDirectory(prefix="front-page-check-") as tmp:
        for number in (1, 2):
            trial = os.path.join(tmp, f"copy-{number}.png")
            with open(trial, "wb") as stream:
                stream.write(payload)
            with open(trial, "rb") as stream:
                seen.append(digest_bytes(stream.read()))
    if seen[0] != expected or seen[1] != expected:
        raise ValueError(
            "determinism self-check failed: repeated copies differ "
            f"({seen[0][:12]} vs {seen[1][:12]} vs {expected[:12]})"
        )


def publish_image(payload: bytes, folder: str, expected: str) -> str:
    """Write the image to <folder>/entry.png and verify the copy."""
    os.makedirs(folder, exist_ok=True)
    destination = os.path.join(folder, FILE_NAME)
    with open(destination, "wb") as stream:
        stream.write(payload)
    with open(destination, "rb") as stream:
        copied = stream.read()
    if digest_bytes(copied) != expected:
        raise ValueError(
            f"copy mismatch: {destination} does not match the source"
        )
    return destination


def describe_image(path: str, payload: bytes, width: int,
                   height: int, digest: str) -> None:
    """Print the verified facts about the entry image."""
    print(f"entry: {path}")
    print(f"size: {len(payload)} bytes")
    print(f"dimensions: {width}x{height}")
    print(f"sha256: {digest}")


def build_parser() -> argparse.ArgumentParser:
    """Define the command-line options for this publisher."""
    parser = argparse.ArgumentParser(
        description=(
            "Publish the news-image-20261126 front page "
            "(entry.png) to /output/entry.png, verified byte for byte."
        )
    )
    parser.add_argument(
        "--output",
        default="/output",
        help="directory to write entry.png into (default: /output)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help=(
            "only run the checks on entry.png (size, PNG header, "
            "IHDR CRC, dimensions, SHA-256) and do not write a copy"
        ),
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    """Run the publisher; return the process exit code."""
    options = build_parser().parse_args(argv)
    path = locate_image()
    try:
        payload = load_image_bytes(path)
    except FileNotFoundError as exc:
        return report_error(str(exc))
    except OSError as exc:
        return report_error(f"cannot read entry image {path}: {exc}")
    try:
        width, height, digest = inspect_image(payload, path)
    except ValueError as exc:
        return report_error(str(exc))
    describe_image(path, payload, width, height, digest)
    if options.verify_only:
        print("verify-only: all checks passed, nothing written")
        return 0
    try:
        duplicate_twice(payload, digest)
    except ValueError as exc:
        return report_error(str(exc))
    print("determinism: two trial copies hash identically")
    try:
        destination = publish_image(payload, options.output, digest)
    except (OSError, ValueError) as exc:
        return report_error(str(exc))
    print(f"wrote: {destination} ({len(payload)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(run())
