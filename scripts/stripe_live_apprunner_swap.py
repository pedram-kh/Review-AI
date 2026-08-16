"""Ticket 6.10 — swap the three Stripe settings on the live App Runner service.

Two different stores are involved, because the project already classified these values
differently back in ticket 4.4 (see `docs/CUTOVER.md`'s secret-vs-config table):

  * `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` are real secrets, living as JSON keys inside
    the Secrets Manager secret `reviewpilot-backend/prod-env-secrets`, referenced by App Runner
    through `RuntimeEnvironmentSecrets`.
  * `STRIPE_PRICE_ID` is public (it appears in every Checkout Session) and lives as a plain
    `RuntimeEnvironmentVariables` entry on the service itself.

That split is why this is one script and not two: App Runner resolves Secrets Manager references
at deployment time, not continuously, so rotating the secret values alone would leave the running
instance on the old key until something triggered a deploy. The `update-service` call that writes
the new price IS that deploy, so ordering the secret write first and the service update second
makes a single rollout carry all three changes.

Safety:
  * Snapshots both stores to disk before writing anything, and prints the paths (that is the
    rollback material referenced in the ticket report).
  * Asserts the secret JSON has exactly the same key set before and after — a swap that silently
    drops `DATABASE_URL` would take production down on the next deploy.
  * Rebuilds `SourceConfiguration` from the live snapshot and changes exactly one env var, rather
    than reconstructing it from memory (the house pattern since tickets 3.2/4.2/4.3).
  * `--apply` required; without it, prints the diff it would make, with secret values shown only
    as `sk_live_…` / `whsec_…` prefixes and lengths, never in full.
"""

import argparse
import copy
import json
import pathlib
import subprocess
import sys
import time

REGION = "eu-west-1"
SECRET_ID = "reviewpilot-backend/prod-env-secrets"
SERVICE_ARN = (
    "arn:aws:apprunner:eu-west-1:049681810267:service/reviewpilot-backend/"
    "e8a2e5664f5040d98880aef80bce73e7"
)
HEALTH_URL = "https://ytjgivwddf.eu-west-1.awsapprunner.com/health"

REPO = pathlib.Path(__file__).resolve().parent.parent
KEY_FILE = REPO / ".env.stripe-live"
SNAPSHOT_DIR = REPO / ".cutover-snapshots"  # gitignored


def aws(*args: str) -> str:
    result = subprocess.run(
        ["aws", *args, "--region", REGION], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        sys.exit(f"AWS call failed: aws {' '.join(args)}\n{result.stderr.strip()}")
    return result.stdout


def read_key_file() -> dict[str, str]:
    values = {}
    for line in KEY_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip()
    return values


def masked(value: str) -> str:
    prefix = value[:8] if len(value) > 8 else "?"
    return f"{prefix}… ({len(value)} chars)"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--price-id", required=True, help="the new live price id from step 2")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    keys = read_key_file()
    live_key = keys.get("STRIPE_LIVE_SECRET_KEY", "")
    webhook_secret = keys.get("STRIPE_LIVE_WEBHOOK_SECRET", "")
    if not live_key.startswith("sk_live_"):
        sys.exit("STRIPE_LIVE_SECRET_KEY is missing or not a live key.")
    if not webhook_secret.startswith("whsec_"):
        sys.exit("STRIPE_LIVE_WEBHOOK_SECRET is missing — run stripe_live_cutover.py first.")
    if not args.price_id.startswith("price_"):
        sys.exit("--price-id does not look like a Stripe price id.")

    SNAPSHOT_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    # --- snapshot both stores -------------------------------------------------------------
    secret_json = aws(
        "secretsmanager", "get-secret-value", "--secret-id", SECRET_ID,
        "--query", "SecretString", "--output", "text",
    )
    secret_path = SNAPSHOT_DIR / f"secrets-{stamp}.json"
    secret_path.write_text(secret_json)
    secret_path.chmod(0o600)

    service_json = aws(
        "apprunner", "describe-service", "--service-arn", SERVICE_ARN, "--output", "json"
    )
    service_path = SNAPSHOT_DIR / f"apprunner-{stamp}.json"
    service_path.write_text(service_json)
    service_path.chmod(0o600)

    print(f"snapshot  secrets   → {secret_path}")
    print(f"snapshot  apprunner → {service_path}\n")

    # --- build the new secret payload -----------------------------------------------------
    current = json.loads(secret_json)
    updated = dict(current)
    updated["STRIPE_SECRET_KEY"] = live_key
    updated["STRIPE_WEBHOOK_SECRET"] = webhook_secret
    if set(updated) != set(current):
        sys.exit("Refusing to write: the secret's key set changed.")

    print("secret    STRIPE_SECRET_KEY     "
          f"{masked(current['STRIPE_SECRET_KEY'])} → {masked(live_key)}")
    print("secret    STRIPE_WEBHOOK_SECRET "
          f"{masked(current['STRIPE_WEBHOOK_SECRET'])} → {masked(webhook_secret)}")
    print(f"          (all {len(updated)} keys preserved)\n")

    # --- build the new SourceConfiguration ------------------------------------------------
    service = json.loads(service_json)["Service"]
    source_config = copy.deepcopy(service["SourceConfiguration"])
    values = source_config["CodeRepository"]["CodeConfiguration"]["CodeConfigurationValues"]
    old_price = values["RuntimeEnvironmentVariables"].get("STRIPE_PRICE_ID")
    values["RuntimeEnvironmentVariables"]["STRIPE_PRICE_ID"] = args.price_id
    print(f"env var   STRIPE_PRICE_ID       {old_price} → {args.price_id}\n")

    if not args.apply:
        print("Plan only — re-run with --apply to write.")
        return

    # --- write ----------------------------------------------------------------------------
    payload_path = SNAPSHOT_DIR / f"new-secret-{stamp}.json"
    payload_path.write_text(json.dumps(updated))
    payload_path.chmod(0o600)
    aws(
        "secretsmanager", "put-secret-value", "--secret-id", SECRET_ID,
        "--secret-string", f"file://{payload_path}",
    )
    payload_path.unlink()
    print("secret    written")

    config_path = SNAPSHOT_DIR / f"source-config-{stamp}.json"
    config_path.write_text(json.dumps(source_config))
    aws(
        "apprunner", "update-service", "--service-arn", SERVICE_ARN,
        "--source-configuration", f"file://{config_path}",
    )
    print("service   update-service accepted — deployment started\n")

    # --- wait for RUNNING -----------------------------------------------------------------
    for _ in range(60):
        status = aws(
            "apprunner", "describe-service", "--service-arn", SERVICE_ARN,
            "--query", "Service.Status", "--output", "text",
        ).strip()
        print(f"          status: {status}")
        if status == "RUNNING":
            break
        if status in ("CREATE_FAILED", "DELETE_FAILED"):
            sys.exit(f"Service entered {status} — roll back from {service_path}")
        time.sleep(15)
    else:
        sys.exit("Timed out waiting for RUNNING.")

    print(f"\nNow verify: curl -s {HEALTH_URL}")


if __name__ == "__main__":
    main()
