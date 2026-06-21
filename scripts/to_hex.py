#!/usr/bin/env python3

import argparse


def to_hex_escapes(text: str) -> str:
    return "".join(f"\\x{byte:02x}" for byte in text.encode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a string to a sequence of \\xNN byte escapes."
    )
    parser.add_argument("text", help="String to convert")
    args = parser.parse_args()

    print(to_hex_escapes(args.text))


if __name__ == "__main__":
    main()
