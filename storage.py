import os
import shutil

# Where runtime JSON data lives. On Railway the container filesystem is
# ephemeral, so mounting a Volume at /data and setting DATA_DIR=/data makes
# economy balances, levels, warnings, giveaways, etc. survive redeploys.
# Without the env var everything keeps working from the repo's data/ folder.
DATA_DIR = os.getenv("DATA_DIR", "data")
BASELINE_DIR = "data"


def path(filename: str) -> str:
    return os.path.join(DATA_DIR, filename)


def bootstrap():
    """Ensure DATA_DIR exists and seed it with the committed baseline configs."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.abspath(DATA_DIR) == os.path.abspath(BASELINE_DIR):
        return
    if not os.path.isdir(BASELINE_DIR):
        return
    for name in os.listdir(BASELINE_DIR):
        if not name.endswith(".json"):
            continue
        target = os.path.join(DATA_DIR, name)
        if not os.path.exists(target):
            shutil.copyfile(os.path.join(BASELINE_DIR, name), target)
            print(f"[Storage] Seeded {target} from baseline", flush=True)
