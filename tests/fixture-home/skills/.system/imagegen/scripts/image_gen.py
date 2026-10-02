import argparse
import json


VALIDATIONS = []


def _validate_size(size, model):
    VALIDATIONS.append((size, model))


def _ensure_api_key(dry_run):
    raise RuntimeError("unpatched credential check")


def main():
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("command")
    parser.add_argument("--model", default="gpt-image-2")
    parser.add_argument("--size", default="auto")
    args, _ = parser.parse_known_args()
    _validate_size(args.size, args.model)
    _ensure_api_key("--dry-run" in sys.argv)
    print(json.dumps({
        "model": args.model,
        "size": args.size,
        "validations": VALIDATIONS,
    }))
    print("fake-imagegen-main")
    return 0
