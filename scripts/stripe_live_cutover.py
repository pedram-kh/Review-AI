"""Ticket 6.10 — create the product/price/webhook objects in the NEW live Stripe account.

Idempotent, in the same sense ticket 4.3's setup was: re-running it must not create a second
"ReviewGuide" product, a second 39 PLN price, or a second webhook endpoint. Run it twice and the
second run should print the same three IDs the first one did.

Safety posture, deliberately paranoid because this is the first script in the project that ever
touches a LIVE Stripe account:

  * The key is read from `.env.stripe-live` (gitignored) and never printed, never logged, never
    passed as a CLI argument (argv is visible in `ps`).
  * A key that doesn't start with `sk_live_` aborts the run. Pointing this at the old sandbox by
    accident would silently create duplicate objects in the account we're migrating away from.
  * `--apply` is required. Without it the script only reports what it *would* do, so the plan can
    be reviewed against the real account state before anything is created (Rule 6, adapted to a
    Stripe API that has no `--dry-run` of its own).
  * The webhook signing secret is written straight to `.env.stripe-live` alongside the key rather
    than printed, because Stripe returns it exactly once (at creation) and a scrollback buffer is
    a bad place for the only copy of a credential.

Usage:
    .venv/bin/python scripts/stripe_live_cutover.py            # plan only
    .venv/bin/python scripts/stripe_live_cutover.py --apply    # create what's missing
"""

import argparse
import pathlib
import sys

import stripe

KEY_FILE = pathlib.Path(__file__).resolve().parent.parent / ".env.stripe-live"
KEY_NAME = "STRIPE_LIVE_SECRET_KEY"
SECRET_NAME = "STRIPE_LIVE_WEBHOOK_SECRET"

PRODUCT_NAME = "ReviewGuide"
# Same tax code the sandbox product carried since CR-1/4.6 — "Software as a service (SaaS) —
# business use". Stripe Tax needs it to pick the right PL VAT treatment.
TAX_CODE = "txcd_10103001"

UNIT_AMOUNT = 3900  # 39.00 PLN, in grosze
CURRENCY = "pln"
INTERVAL = "month"
TAX_BEHAVIOR = "exclusive"  # 39 zł is NETTO; VAT is added on top (ToS § 7.2)

WEBHOOK_URL = "https://ytjgivwddf.eu-west-1.awsapprunner.com/api/billing/webhook"
WEBHOOK_EVENTS = [
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
]


def read_key_file() -> dict[str, str]:
    if not KEY_FILE.exists():
        sys.exit(f"{KEY_FILE.name} is missing — see ticket 6.10's key-handoff step.")
    values = {}
    for line in KEY_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip()
    return values


def load_live_key() -> str:
    key = read_key_file().get(KEY_NAME, "")
    if not key or key == "sk_live_PASTE_HERE":
        sys.exit(
            f"{KEY_NAME} is still the placeholder — the live key has not been pasted yet."
        )
    if key.startswith("sk_test_"):
        sys.exit(
            "That is a TEST-mode key. Toggle test mode OFF in the new account's dashboard and "
            "copy the sk_live_ key instead."
        )
    if not key.startswith("sk_live_"):
        sys.exit("Refusing to run: the key does not look like a Stripe live secret key.")
    return key


def append_webhook_secret(secret: str) -> None:
    existing = read_key_file()
    if existing.get(SECRET_NAME):
        # Never silently clobber a secret we can't re-read from Stripe afterwards.
        sys.exit(
            f"{SECRET_NAME} is already set in {KEY_FILE.name} — refusing to overwrite. Clear it by "
            "hand if you genuinely intend to recreate the endpoint."
        )
    with KEY_FILE.open("a") as fh:
        fh.write(
            f"\n# Written by scripts/stripe_live_cutover.py — Stripe returns this exactly once.\n"
            f"{SECRET_NAME}={secret}\n"
        )


def find_product() -> stripe.Product | None:
    for product in stripe.Product.list(active=True, limit=100).auto_paging_iter():
        if product.name == PRODUCT_NAME:
            return product
    return None


def find_price(product_id: str) -> stripe.Price | None:
    for price in stripe.Price.list(product=product_id, active=True, limit=100).auto_paging_iter():
        if (
            price.unit_amount == UNIT_AMOUNT
            and price.currency == CURRENCY
            and price.recurring
            and price.recurring.interval == INTERVAL
            and price.tax_behavior == TAX_BEHAVIOR
        ):
            return price
    return None


def find_webhook() -> stripe.WebhookEndpoint | None:
    for endpoint in stripe.WebhookEndpoint.list(limit=100).auto_paging_iter():
        if endpoint.url == WEBHOOK_URL:
            return endpoint
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply", action="store_true", help="actually create the missing objects (default: plan)"
    )
    args = parser.parse_args()
    stripe.api_key = load_live_key()

    account = stripe.Account.retrieve()
    # StripeObject subclasses dict but proxies attribute access, so `.get` resolves to a missing
    # API field rather than dict.get — index it instead.
    profile = account["business_profile"] if "business_profile" in account else None
    account_name = (profile and profile["name"]) or "unnamed"
    print(f"Account:   {account.id} ({account_name})")
    print(f"Plan-only: {not args.apply}\n")

    product = find_product()
    if product:
        print(f"product  REUSE   {product.id} ({product.name})")
    elif args.apply:
        product = stripe.Product.create(name=PRODUCT_NAME, tax_code=TAX_CODE)
        print(f"product  CREATED {product.id}")
    else:
        print(f"product  WOULD CREATE  name={PRODUCT_NAME} tax_code={TAX_CODE}")

    price = find_price(product.id) if product else None
    if price:
        amount = f"{price.unit_amount / 100:.2f} {price.currency.upper()}"
        print(f"price    REUSE   {price.id} ({amount})")
    elif args.apply and product:
        price = stripe.Price.create(
            product=product.id,
            unit_amount=UNIT_AMOUNT,
            currency=CURRENCY,
            recurring={"interval": INTERVAL},
            tax_behavior=TAX_BEHAVIOR,
        )
        print(f"price    CREATED {price.id}")
    else:
        print(
            f"price    WOULD CREATE  {UNIT_AMOUNT / 100:.2f} {CURRENCY.upper()}/{INTERVAL} "
            f"tax_behavior={TAX_BEHAVIOR}"
        )

    endpoint = find_webhook()
    if endpoint:
        # Stripe only returns `secret` on the creation response, so an endpoint that already
        # exists is only usable if we already captured its secret. Say so plainly instead of
        # producing a config that silently fails every signature check in production.
        have_secret = bool(read_key_file().get(SECRET_NAME))
        state = "REUSE" if have_secret else "EXISTS-BUT-SECRET-UNKNOWN"
        print(f"webhook  {state}   {endpoint.id} → {endpoint.url}")
        if not have_secret:
            print(
                "         Its signing secret cannot be read back from the API. Delete the endpoint "
                "in the dashboard and re-run, or paste the secret into "
                f"{KEY_FILE.name} as {SECRET_NAME}."
            )
    elif args.apply:
        endpoint = stripe.WebhookEndpoint.create(url=WEBHOOK_URL, enabled_events=WEBHOOK_EVENTS)
        append_webhook_secret(endpoint.secret)
        print(f"webhook  CREATED {endpoint.id} → {endpoint.url}")
        print(f"         signing secret written to {KEY_FILE.name} (not printed)")
    else:
        print(f"webhook  WOULD CREATE  {WEBHOOK_URL}")
        for event in WEBHOOK_EVENTS:
            print(f"                       + {event}")

    if args.apply and price:
        print(f"\nSTRIPE_PRICE_ID for App Runner: {price.id}")


if __name__ == "__main__":
    main()
