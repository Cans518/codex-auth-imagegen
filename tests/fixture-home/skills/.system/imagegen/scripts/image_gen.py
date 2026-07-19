def _ensure_api_key(dry_run):
    raise RuntimeError("unpatched credential check")


def main():
    import sys

    _ensure_api_key("--dry-run" in sys.argv)
    print("fake-imagegen-main")
    return 0
