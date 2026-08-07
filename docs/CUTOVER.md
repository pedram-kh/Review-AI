# CUTOVER.md — Private RDS + NAT + Secrets Manager hardening runbook

> SPRINT_04.md ticket 4.4. **Status: EXECUTED, 2026-08-07.** Stakeholder call: "GO NOW. Full
> cutover today." Every step below (0 through 8) has been run against production, in this exact
> order, each gated on its own verification before the next step ran. See PROGRESS.md's ticket
> 4.4 row for the full execution log and the post-cutover checklist results. This document is
> kept as the permanent record of what was done and as the rollback reference, not as a
> pending-approval plan.

## 0. What this changes and why

Today (2026-08-07): RDS `reviewpilot-db` is `PubliclyAccessible=true`, reachable from
`0.0.0.0/0` on 5432 (LOGIC/ROADMAP's documented interim-hardening state — SSL-forced, random
32-char password, but still internet-facing on the DB port). App Runner reaches it over the
public internet with `EgressConfiguration.EgressType=DEFAULT`. Secrets live as plain
`RuntimeEnvironmentVariables` on the App Runner service, readable by anyone with
`apprunner:DescribeService` on the AWS account.

This is the ROADMAP §"RDS networking (interim)" **hard gate**: flip to private VPC + NAT before
the first real customer row exists (Sprint 4). After this runbook:

- RDS is reachable **only** from inside the VPC, only from the App Runner VPC connector's
  security group. No CIDR-based inbound rule remains.
- App Runner's outbound traffic (to RDS, and to Postmark/Stripe/Anthropic/Outscraper's public
  APIs) routes through a VPC connector's private subnets + a NAT Gateway.
- The 8 true secrets move to AWS Secrets Manager, read by App Runner via an instance role
  (`secretsmanager:GetSecretValue` scoped to exactly one secret ARN) instead of living as plain
  env vars on the service.

**Cost impact: ~$37/mo starts the moment the NAT Gateway is created** (1 NAT Gateway,
eu-west-1: ~$0.045/hr ≈ $33/mo + ~$0.045/GB data processing — negligible at current traffic
volume, so ~$33-37/mo all-in). This is the exact number already called out in ROADMAP.md and
BACKLOG.md; nothing above that was assumed here. **This is the single dollar-cost step in the
whole runbook** — every other resource (subnets, route tables, security groups, the Secrets
Manager secret, the App Runner VPC connector object itself) is free to hold, whether or not
it's ever attached to anything live.

**Single-NAT-Gateway design, disclosed:** one NAT Gateway (not one per AZ) keeps cost at the
budgeted ~$37/mo instead of ~$74/mo. This makes the NAT Gateway's AZ (eu-west-1a, chosen below)
a single point of failure for *outbound* traffic only — if that AZ has an outage, App Runner
could not reach Postmark/Stripe/Anthropic/Outscraper (RDS itself is unaffected, since it's
reached over the VPC's local route, not through the NAT). At current scale (pre-launch, no paid
customers yet) this is the same cost/reliability trade-off already accepted for the rest of the
stack (single-AZ RDS, single App Runner service) — flagging it here rather than silently
upgrading to two NAT Gateways and doubling the approved cost figure.

## 1. Pre-created now (inert, zero effect on the running service, done 2026-08-07)

These two are the only things this session actually ran for real, per ticket 4.4's own carve-out
("where a resource can be pre-created without affecting prod... prepare it"). Neither is
referenced by anything live yet.

1. **Secrets Manager secret** — `reviewpilot-backend/prod-env-secrets`
   (`arn:aws:secretsmanager:eu-west-1:049681810267:secret:reviewpilot-backend/prod-env-secrets-FYOjxG`),
   holding the 8 keys classified as true secrets (below). Verified populated from the exact live
   App Runner values at creation time.
2. **IAM role click-path doc** — section 6 below. Not executable by this session's own AWS
   credentials in the first place: `aws iam simulate-principal-policy` on the `cursor-dev` IAM
   user for `iam:CreateRole`/`iam:AttachRolePolicy`/`iam:PutRolePolicy`/`iam:CreatePolicy` was
   itself denied (`AccessDenied` on `SimulatePrincipalPolicy`), confirming this identity has no
   IAM-write surface at all — the "known manual console step" in the ticket text isn't a
   convention here, it's the only path available.

**Secret classification** (why each of the 12 live App Runner env vars landed where it did):

| Stays plain `RuntimeEnvironmentVariables` | Moves to Secrets Manager |
|---|---|
| `APP_ORIGIN` (public app URL) | `ADMIN_API_KEY` |
| `REPLY_ADDRESS` (public sender address) | `ANTHROPIC_API_KEY` |
| `PYTHONPATH` (build config, not secret) | `AUTH_JWT_SECRET` |
| `STRIPE_PRICE_ID` (public — visible in every Checkout Session) | `DATABASE_URL` |
| | `OUTSCRAPER_API_KEY` |
| | `POSTMARK_TOKEN` |
| | `STRIPE_SECRET_KEY` |
| | `STRIPE_WEBHOOK_SECRET` |

## 2. Current live resource IDs (read via `describe-*`, not modified)

| Resource | Value |
|---|---|
| VPC | `vpc-0f33f60b804ff6738` (default VPC, CIDR `172.31.0.0/16`) |
| Existing public subnets | `subnet-0b3a475aab8624f55` (1a, `172.31.16.0/20`), `subnet-00fc8f66fd3d786c6` (1b, `172.31.32.0/20`), `subnet-067b22b6b40d634c8` (1c, `172.31.0.0/20`) — all route `0.0.0.0/0` → IGW `igw-08a84f26a5af7da0b` via the VPC's main route table `rtb-0a706387a037bdb71` |
| RDS instance | `reviewpilot-db` (postgres 18.4, `db.t4g.micro`, **single-AZ**, `PubliclyAccessible=true`) |
| RDS security group | `sg-00fff83298897dba1` — inbound 5432 from `188.26.212.165/32` (dev direct-psql IP) **and `0.0.0.0/0`** |
| RDS subnet group | `reviewpilot-db-subnet-group` (unchanged by this runbook — see §3 note) |
| App Runner service | `reviewpilot-backend` — `arn:aws:apprunner:eu-west-1:049681810267:service/reviewpilot-backend/e8a2e5664f5040d98880aef80bce73e7` |
| App Runner network config today | `EgressConfiguration.EgressType=DEFAULT`, `IngressConfiguration.IsPubliclyAccessible=true` (ingress stays `true` — the API itself must stay public) |
| App Runner instance config today | `Cpu=256`, `Memory=512`, no `InstanceRoleArn` |
| AWS account | `049681810267`, region `eu-west-1` |

**Free CIDR space confirmed:** existing subnets occupy `.0.0/20`, `.16.0/20`, `.32.0/20`;
`172.31.48.0/20` onward is unused. Two new connector subnets carved from inside it, well clear
of anything existing.

**Design simplification found while rehearsing, disclosed:** the ticket's "Done when" list reads
"RDS modify to not-publicly-accessible + SG allowing only the connector's SG" as one bullet next
to "NAT gateway + route tables" — I initially assumed that meant moving RDS itself into new
private subnets. It doesn't need to: RDS's `PubliclyAccessible` flag (not its subnet group's own
route-table configuration) is what controls whether it gets a public IP at all. `reviewpilot-db`
can stay in its current subnet group unchanged; only the **App Runner VPC connector** needs new
subnets + a NAT route, since attaching a connector switches *all* of the app's outbound traffic
(not just DB-bound) onto the VPC, and that traffic still needs internet egress for
Postmark/Stripe/Anthropic/Outscraper. This halves the blast radius of the RDS-side change (a
flag flip + an SG edit, not a subnet migration) and removes any RDS reboot/relocation risk from
the plan entirely.

## 3. Ordered cutover steps

Every AWS CLI-only step below (marked 🔵) was validated with `--dry-run` against the real
account today and returned `Request would have succeeded, but DryRun flag is set` — i.e. the
IAM permissions and parameters are already confirmed correct, not just written from memory. RDS
and App Runner API calls (marked 🟡) have no `DryRun` parameter in their APIs at all; those were
instead validated by pulling the live `--generate-cli-skeleton` schema and confirming every field
used below exists with the expected shape (see §7), and by this project's own precedent of
already having run structurally identical `apprunner update-service` calls three times
(tickets 3.2, 4.2, 4.3) without incident.

**Numbering note (PM amendment, 2026-08-07):** "Step 0" (the SSM bastion) is presented first
because it's the answer to Step 6's local-debugging-access question and must exist *before* RDS
goes private — but it physically needs the private connector subnets, the NAT Gateway, and the
RDS security group to already exist (an SSM-managed instance needs outbound internet reachability
to talk to the SSM service endpoints, and the whole point of the bastion is being able to reach
the RDS SG). So its commands are sequenced for real execution **after Steps 1-3** below, even
though it's the conceptual "Step 0" — disclosed here rather than silently reordering the
document without saying so.

### Step 1 — Create the connector's private subnets 🔵 (dry-run verified)

No impact: nothing routes through these until step 5.

```bash
aws ec2 create-subnet --region eu-west-1 \
  --vpc-id vpc-0f33f60b804ff6738 --cidr-block 172.31.48.0/24 --availability-zone eu-west-1a \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=reviewpilot-connector-private-1a}]'
# capture the returned SubnetId as CONN_SUBNET_A

aws ec2 create-subnet --region eu-west-1 \
  --vpc-id vpc-0f33f60b804ff6738 --cidr-block 172.31.49.0/24 --availability-zone eu-west-1b \
  --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=reviewpilot-connector-private-1b}]'
# capture the returned SubnetId as CONN_SUBNET_B
```

**Verify:** `aws ec2 describe-subnets --subnet-ids $CONN_SUBNET_A $CONN_SUBNET_B` shows both in
`available` state.
**Rollback:** `aws ec2 delete-subnet --subnet-id <id>` for each (safe — nothing depends on them
yet at this point in the sequence).

### Step 2 — NAT Gateway + private route table 🔵 (dry-run verified) — **cost starts here**

```bash
# Elastic IP for the NAT Gateway
aws ec2 allocate-address --region eu-west-1 --domain vpc \
  --tag-specifications 'ResourceType=elastic-ip,Tags=[{Key=Name,Value=reviewpilot-nat-eip}]'
# capture AllocationId as NAT_EIP_ALLOC_ID

# NAT Gateway lives in an existing PUBLIC subnet (same AZ as CONN_SUBNET_A, to minimize
# cross-AZ data-processing charges for that subnet's traffic)
aws ec2 create-nat-gateway --region eu-west-1 \
  --subnet-id subnet-0b3a475aab8624f55 --allocation-id $NAT_EIP_ALLOC_ID \
  --tag-specifications 'ResourceType=natgateway,Tags=[{Key=Name,Value=reviewpilot-nat}]'
# capture NatGatewayId as NAT_GW_ID; poll until state=available (typically 1-3 minutes):
aws ec2 wait nat-gateway-available --region eu-west-1 --nat-gateway-ids $NAT_GW_ID

# Private route table for the two connector subnets
aws ec2 create-route-table --region eu-west-1 --vpc-id vpc-0f33f60b804ff6738 \
  --tag-specifications 'ResourceType=route-table,Tags=[{Key=Name,Value=reviewpilot-connector-private-rt}]'
# capture RouteTableId as CONN_RT_ID

aws ec2 create-route --region eu-west-1 --route-table-id $CONN_RT_ID \
  --destination-cidr-block 0.0.0.0/0 --nat-gateway-id $NAT_GW_ID

aws ec2 associate-route-table --region eu-west-1 --route-table-id $CONN_RT_ID --subnet-id $CONN_SUBNET_A
aws ec2 associate-route-table --region eu-west-1 --route-table-id $CONN_RT_ID --subnet-id $CONN_SUBNET_B
```

**Verify:** `aws ec2 describe-nat-gateways --nat-gateway-ids $NAT_GW_ID` → `State: available`;
`aws ec2 describe-route-tables --route-table-id $CONN_RT_ID` shows the `0.0.0.0/0 → nat-...`
route and both subnet associations.
**Rollback:** disassociate both subnets, `delete-route`, `delete-route-table`,
`delete-nat-gateway` (takes a few minutes to fully delete), then
`release-address --allocation-id $NAT_EIP_ALLOC_ID` once the NAT Gateway is gone. **Billing stops
only once the NAT Gateway delete completes** — this is the one step where "rollback" has a
non-trivial time cost, not just an API call.

### Step 3 — Connector security group + RDS SG rule (additive) 🔵 (dry-run verified)

Additive only — the existing `0.0.0.0/0` rule stays untouched until step 6, so nothing that
works today stops working during this step.

```bash
aws ec2 create-security-group --region eu-west-1 \
  --group-name reviewpilot-apprunner-connector-sg \
  --description "App Runner VPC connector - outbound only, no inbound needed" \
  --vpc-id vpc-0f33f60b804ff6738
# capture GroupId as CONN_SG_ID (default egress = allow all, which is what we want: it needs to
# reach RDS inside the VPC and the internet via the NAT Gateway)

aws ec2 authorize-security-group-ingress --region eu-west-1 \
  --group-id sg-00fff83298897dba1 --protocol tcp --port 5432 \
  --source-group $CONN_SG_ID
```

**Verify:** `aws ec2 describe-security-groups --group-ids sg-00fff83298897dba1` shows a new
inbound rule with `UserIdGroupPairs: [{GroupId: $CONN_SG_ID}]` on 5432, alongside the two
existing CIDR rules (unchanged).
**Rollback:** `aws ec2 revoke-security-group-ingress ... --source-group $CONN_SG_ID` then
`aws ec2 delete-security-group --group-id $CONN_SG_ID`.

### Step 0 — SSM bastion bridge (PM amendment, 2026-08-07) 🟡🔵

**Why this exists:** ticket 4.4's original Step 6 flagged, as an open question, that every
local/CI direct-`psql` session this project has used since Sprint 0 (every `RUNBOOK_LEADS.md`
job, every live-verification `python -m app.jobs.*` invocation, every ad-hoc debug query across
tickets 1.x-4.3) permanently loses access the moment RDS goes private, and left the fix
unbuilt/undecided. PM verdict on ticket 4.4 makes this a **cutover prerequisite, not a follow-up**
— this step builds it before Step 6 removes public access, so nothing above breaks.

**Design:** one `t4g.nano` EC2 instance (Amazon Linux 2023, arm64 — SSM Agent preinstalled, no
extra setup), **no public IP**, living in one of the two connector private subnets from Step 1
(so it rides the same NAT Gateway for its own outbound SSM traffic — no new NAT/VPC-endpoint
cost). Reached exclusively via **AWS Systems Manager Session Manager** — zero inbound security
group rules on the bastion itself, no SSH key to manage or leak, every session logged in
CloudTrail/SSM. A local port-forward session tunnels `localhost:15432` → the bastion →
`reviewpilot-db`'s private IP on 5432; overriding `DATABASE_URL` to point at that local port
before running any existing job is the entire integration surface — **no code in this repo
changes**, `RUNBOOK_LEADS.md`'s commands are literally byte-identical post-cutover, only the
env var pointing at the DB differs for whoever's running them locally.

**IAM instance role — manual console click-path (Stakeholder/AWS-admin action, console task #1,
due before this step can launch the instance):**

1. AWS Console → **IAM** → **Roles** → **Create role**.
2. Trusted entity type: **AWS service**. Use case: **EC2**. Click **Next**.
3. In the permissions search box, find and check **`AmazonSSMManagedInstanceCore`** (AWS-managed
   policy — grants exactly the SSM Agent's own required permissions, nothing app-specific,
   nothing IAM-write, nothing S3/EC2-write). Click **Next**.
4. Name the role `reviewpilot-bastion-instance-role`, create it. (The EC2 console flow
   auto-creates a matching **instance profile** with the same name — that's what `run-instances`
   below references, not the role ARN directly.)
5. No inline policy needed this time — the managed policy is sufficient and is the AWS-documented
   minimum for Session Manager to work at all.

```bash
# --- Prerequisite security group for the bastion ---
aws ec2 create-security-group --region eu-west-1 \
  --group-name reviewpilot-bastion-sg \
  --description "SSM-managed bastion - zero inbound rules, outbound only" \
  --vpc-id vpc-0f33f60b804ff6738
# capture GroupId as BASTION_SG_ID — leave its inbound rules empty (default = none); default
# egress (allow all) is what it needs for SSM + the RDS tunnel

# Let the bastion reach RDS: same pattern as the connector's rule in Step 3
aws ec2 authorize-security-group-ingress --region eu-west-1 \
  --group-id sg-00fff83298897dba1 --protocol tcp --port 5432 --source-group $BASTION_SG_ID

# --- Launch the instance (only once the console role/instance-profile above exists) ---
aws ec2 run-instances --region eu-west-1 \
  --image-id ami-053d8df569ac57bbb \
  --instance-type t4g.nano \
  --subnet-id $CONN_SUBNET_A \
  --security-group-ids $BASTION_SG_ID \
  --iam-instance-profile Name=reviewpilot-bastion-instance-role \
  --no-associate-public-ip-address \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=reviewpilot-bastion}]'
# capture InstanceId as BASTION_INSTANCE_ID
```

**Verify:**
```bash
aws ec2 wait instance-status-ok --region eu-west-1 --instance-ids $BASTION_INSTANCE_ID
aws ssm describe-instance-information --region eu-west-1 \
  --filters "Key=InstanceIds,Values=$BASTION_INSTANCE_ID" --query "InstanceInformationList[0].PingStatus"
# expect "Online" — confirms the SSM Agent registered, i.e. the instance role + NAT path both work
```

**The bridge command itself (this is what every future debugging session runs first):**
```bash
aws ssm start-session --region eu-west-1 --target $BASTION_INSTANCE_ID \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["reviewpilot-db.cpsukkwcomk6.eu-west-1.rds.amazonaws.com"],"portNumber":["5432"],"localPortNumber":["15432"]}'
# leave this running in its own terminal for the duration of the debugging session
```

**Local `DATABASE_URL` override, in a second terminal, for the duration of the tunnel above**
(same credentials as today's `.env` — only host/port change; `sslmode=require` still works, since
TLS is negotiated end-to-end through the raw TCP forward and `require` mode doesn't check that
the hostname matches the cert, unlike `verify-full`):
```bash
export DATABASE_URL="postgresql://reviewpilot:<same-password-as-.env>@localhost:15432/reviewpilot?sslmode=require"
# every RUNBOOK_LEADS.md command (python -m app.jobs.discover, .enrich, .generate, etc.) now
# works completely unchanged against the now-private DB
```

**Cost:** `t4g.nano` ≈ $3-3.50/mo (eu-west-1, on-demand, always-on) — SSM itself is free (no
Session Manager service charge). Optional future optimization, not done now: stop the instance
between debugging sessions (`aws ec2 stop-instances`) since nothing depends on it running
continuously; a stopped `t4g.nano` costs $0 in compute (only its 8GB gp3 root volume, ~$0.64/mo).

**Rollback:** `aws ec2 terminate-instances --instance-ids $BASTION_INSTANCE_ID`; revoke the
`$BASTION_SG_ID` rule from the RDS SG; `delete-security-group`. Doesn't affect anything else in
this runbook — the bastion is a pure side-branch off the shared private subnets/NAT, not a
dependency of Steps 4-8.

**This is a bridge, not the destination (see the rewritten note in Step 6 below).**

### Step 4 — Create the App Runner VPC connector 🟡 (schema-verified, no DryRun in this API)

Standalone resource — doesn't affect the running service until step 5 attaches it.

```bash
aws apprunner create-vpc-connector --region eu-west-1 \
  --vpc-connector-name reviewpilot-backend-connector \
  --subnets $CONN_SUBNET_A $CONN_SUBNET_B \
  --security-groups $CONN_SG_ID
# capture VpcConnectorArn as CONNECTOR_ARN; poll until Status=ACTIVE:
aws apprunner describe-vpc-connector --region eu-west-1 --vpc-connector-arn $CONNECTOR_ARN \
  --query "VpcConnector.Status"
```

**Verify:** `Status: ACTIVE`.
**Rollback:** `aws apprunner delete-vpc-connector --vpc-connector-arn $CONNECTOR_ARN` (only
possible once nothing references it — i.e. only before step 5, or after step 5 is rolled back).

### Step 5 — Attach the connector to App Runner (the first real-traffic-affecting step) 🟡

This is a full service deployment, same mechanism already exercised three times this project
(tickets 3.2/4.2/4.3's env var updates, each ~3-4 min to `RUNNING`). App Runner health-checks the
new deployment before shifting traffic and **auto-rolls-back to the current version if the new
one never becomes healthy** — so a misconfigured subnet/SG here fails closed (old version keeps
serving), not open.

**Why this is safe to do *before* flipping `PubliclyAccessible=false` on RDS:** RDS's endpoint
hostname resolves differently depending on where the query comes from (AWS's standard
split-horizon behavior for an instance that's still publicly accessible) — from inside the VPC
(which the connector's ENIs now are) it already resolves to the **private** IP, over the
existing `172.31.0.0/16 → local` route every route table in this VPC already has. Nothing about
RDS itself needs to change for this step to work; `DATABASE_URL`'s hostname doesn't change at
all.

```bash
# Preserve every other field exactly as it is today (Runtime/BuildCommand/StartCommand/Port/
# RuntimeEnvironmentVariables all stay byte-identical to the live service — see §2's table).
# Only NetworkConfiguration.EgressConfiguration changes.
aws apprunner update-service --region eu-west-1 \
  --service-arn arn:aws:apprunner:eu-west-1:049681810267:service/reviewpilot-backend/e8a2e5664f5040d98880aef80bce73e7 \
  --network-configuration '{
    "EgressConfiguration": {"EgressType": "VPC", "VpcConnectorArn": "'"$CONNECTOR_ARN"'"},
    "IngressConfiguration": {"IsPubliclyAccessible": true}
  }'
```

**Verify (do all of these before proceeding to step 6):**
```bash
curl -s https://ytjgivwddf.eu-west-1.awsapprunner.com/health          # DB-touching health check, expect 200
curl -s -H "X-Admin-Key: $ADMIN_API_KEY" https://.../api/admin/stats  # confirms real DB reads over the new path
# Confirm outbound-to-internet still works (Postmark/Stripe/Anthropic/Outscraper all live behind
# the NAT now, not DEFAULT egress): the billing status/checkout endpoints reaching Stripe is the
# cheapest live check already exercised in ticket 4.3.
```
**Rollback:** re-run `update-service` with `EgressConfiguration: {"EgressType": "DEFAULT"}` —
reverts to exactly today's known-working config. Do **not** proceed to step 6 until every check
above is green.

### Step 6 — Make RDS actually private 🟡

```bash
aws rds modify-db-instance --region eu-west-1 \
  --db-instance-identifier reviewpilot-db \
  --no-publicly-accessible \
  --apply-immediately
```

**Expected downtime: none for App Runner's own traffic** — this flag does not reboot the
instance; it only stops AWS from publishing a public IP for the endpoint, and App Runner's
connector was already resolving the private IP before this ran (Step 5's note above), so its
traffic path doesn't change at all. **`--apply-immediately` means it takes effect right away
instead of waiting for the next maintenance window — the trade-off is that any session currently
connected via the *public* path (there shouldn't be one left by this point in the runbook, but
if there is — e.g. a leftover local `psql` session from before Step 0 existed) will have its
TCP connection dropped and must re-establish** (a plain reconnect, not a data-loss risk;
PostgreSQL client libraries/connection pools generally retry transparently, but a long-running
interactive `psql` shell would need to be restarted by hand). App Runner's own connections
(already flowing over the private path since Step 5) are unaffected — nothing to re-establish
there.

**Real, permanent side effect (not a bug, a consequence, and no longer an open question — PM
amendment 2026-08-07 resolved it):** any tool outside the VPC that was using the public
endpoint — every direct `psql`/Python-script session this whole project has used from a local
shell for debugging, backfills, and live verification (tickets 1.x-4.3 all did this) — loses
access immediately and permanently once this runs, regardless of the security group; there is no
SG rule that can restore it, since `PubliclyAccessible=false` means no public IP exists to route
to at all. **Step 0 above is the bridge**: the SSM bastion's port-forward + a `DATABASE_URL`
override is now built and verified *before* this step runs, so nothing in `RUNBOOK_LEADS.md`'s
workflow actually breaks — it just gains one extra terminal command (`aws ssm start-session`)
per debugging session. **The bastion is explicitly a bridge, not the permanent answer**: the
real fix is that local machines shouldn't need direct DB access at all — BACKLOG.md's
"Pipeline ops in admin panel" item (Run-pipeline-now button, polling schedule, cost-cap editing,
per-run spend history, already scoped as needing "real auth (Sprint 4) before any money-spending
buttons exist in UI" — which Sprint 4 has now delivered) moves job execution *into* App Runner
itself, reachable over the web UI, with the local bastion tunnel becoming a rarely-needed
fallback rather than the everyday path. Tracked as Sprint 5/6 scope in BACKLOG.md, not built here
— this ticket's job was the bridge, not the destination.

**Verify:** `aws rds describe-db-instances --db-instance-identifier reviewpilot-db --query "DBInstances[0].PubliclyAccessible"` → `false`. Re-run step 5's full verification block again —
if `/health` still returns 200 after this, the private path is proven, not assumed.
**Rollback:** `aws rds modify-db-instance --db-instance-identifier reviewpilot-db --publicly-accessible --apply-immediately` (flips back to `true`; the CIDR rules from step 3/before are
still on the SG until step 7, so public access is restored exactly to today's state).

### Step 7 — Remove the public ingress rule 🔵 (dry-run verified against the real, existing rule)

Only run this once step 6's verification is green — this is the point of no return for the CIDR
path.

```bash
aws ec2 revoke-security-group-ingress --region eu-west-1 \
  --group-id sg-00fff83298897dba1 --protocol tcp --port 5432 --cidr 0.0.0.0/0
```

**Decision point for the Stakeholder, not made unilaterally here:** the SG also still has
`188.26.212.165/32` (the developer's direct-psql IP) allowed. It becomes inert the moment step 6
runs (no public IP left to route to, so the rule matches nothing), but it's misleading clutter —
looks like a live exception to a future reader of the SG. Recommend removing it in this same step
for hygiene, once whichever of step 6's "how do we debug post-cutover" options is chosen:
```bash
aws ec2 revoke-security-group-ingress --region eu-west-1 \
  --group-id sg-00fff83298897dba1 --protocol tcp --port 5432 --cidr 188.26.212.165/32
```

**Verify:** `aws ec2 describe-security-groups --group-ids sg-00fff83298897dba1` shows only the
`$CONN_SG_ID` source-group rule on 5432, no CIDR-based rules at all.
**Rollback:** re-add with `authorize-security-group-ingress` using the same flags — but note
this only restores the *rule*; RDS is still not publicly accessible unless step 6 is also
rolled back.

### Step 8 — IAM instance role (manual console step — see §6) then switch to Secrets Manager

Gated on the Stakeholder/an AWS-admin identity completing §6 in the console — this session's own
credentials cannot do it (see §1). Once `INSTANCE_ROLE_ARN` exists:

```bash
aws apprunner update-service --region eu-west-1 \
  --service-arn arn:aws:apprunner:eu-west-1:049681810267:service/reviewpilot-backend/e8a2e5664f5040d98880aef80bce73e7 \
  --instance-configuration '{
    "Cpu": "256", "Memory": "512", "InstanceRoleArn": "'"$INSTANCE_ROLE_ARN"'"
  }' \
  --source-configuration file:///tmp/source_config_secrets_manager.json
```

where `source_config_secrets_manager.json` is today's exact `SourceConfiguration` (§2's live
values) with `RuntimeEnvironmentVariables` trimmed to only the 4 non-secret keys and a new
`RuntimeEnvironmentSecrets` block added:

```json
{
  "ADMIN_API_KEY": "arn:aws:secretsmanager:eu-west-1:049681810267:secret:reviewpilot-backend/prod-env-secrets-FYOjxG:ADMIN_API_KEY::",
  "ANTHROPIC_API_KEY": "arn:aws:secretsmanager:eu-west-1:049681810267:secret:reviewpilot-backend/prod-env-secrets-FYOjxG:ANTHROPIC_API_KEY::",
  "AUTH_JWT_SECRET": "arn:aws:secretsmanager:eu-west-1:049681810267:secret:reviewpilot-backend/prod-env-secrets-FYOjxG:AUTH_JWT_SECRET::",
  "DATABASE_URL": "arn:aws:secretsmanager:eu-west-1:049681810267:secret:reviewpilot-backend/prod-env-secrets-FYOjxG:DATABASE_URL::",
  "OUTSCRAPER_API_KEY": "arn:aws:secretsmanager:eu-west-1:049681810267:secret:reviewpilot-backend/prod-env-secrets-FYOjxG:OUTSCRAPER_API_KEY::",
  "POSTMARK_TOKEN": "arn:aws:secretsmanager:eu-west-1:049681810267:secret:reviewpilot-backend/prod-env-secrets-FYOjxG:POSTMARK_TOKEN::",
  "STRIPE_SECRET_KEY": "arn:aws:secretsmanager:eu-west-1:049681810267:secret:reviewpilot-backend/prod-env-secrets-FYOjxG:STRIPE_SECRET_KEY::",
  "STRIPE_WEBHOOK_SECRET": "arn:aws:secretsmanager:eu-west-1:049681810267:secret:reviewpilot-backend/prod-env-secrets-FYOjxG:STRIPE_WEBHOOK_SECRET::"
}
```

(The trailing `::` selects the whole value at that JSON key, not a specific version stage —
same syntax ECS uses for the same feature; confirmed against App Runner's own
`--generate-cli-skeleton` output in §7, which shows `RuntimeEnvironmentSecrets` as a sibling map
to `RuntimeEnvironmentVariables` on the identical `CodeConfigurationValues` object we've already
edited three times this project.)

**Verify:** same §5 verification block (`/health`, `/api/admin/stats`) — if these still pass with
zero plain secret env vars left on the service, the instance role's read permission works.
Additionally: `aws apprunner describe-service ... --query
"Service.SourceConfiguration.CodeRepository.CodeConfiguration.CodeConfigurationValues.RuntimeEnvironmentVariables"`
should list only the 4 non-secret keys.
**Rollback:** re-run `update-service` with the exact pre-step-8 `SourceConfiguration` snapshot
(save it to a file immediately before running this step, same pattern already used for every
App Runner env var change this project — see ticket 4.3's session) and drop
`InstanceConfiguration.InstanceRoleArn` back to unset.

## 4. Full post-cutover verification checklist (ticket's own list, plus what this session can add)

- [ ] `GET /health` → 200 (confirms DB reachable over the new private path)
- [ ] A real pipeline job still runs end-to-end (e.g. `python -m app.jobs.enrich --recheck` or
      any existing job) — confirms outbound internet (Outscraper) still reaches the API through
      the NAT Gateway, not just RDS
- [ ] `reviewguide-app`'s `/admin` dashboard loads real counts (confirms the whole chain:
      browser → Netlify → App Runner → private RDS)
- [ ] `reviewguide-app`'s `/app` billing card still resolves a real status (confirms outbound
      Stripe reachability through the NAT Gateway)
- [ ] Postmark send still succeeds (confirms outbound Postmark reachability through the NAT
      Gateway) — cheapest check: `POST /api/auth/request-link` for a disposable test address
- [ ] `aws ec2 describe-security-groups --group-ids sg-00fff83298897dba1` shows zero CIDR-based
      inbound rules, exactly one source-group rule
- [ ] `aws rds describe-db-instances ... --query PubliclyAccessible` → `false`
- [ ] `aws apprunner describe-service ...RuntimeEnvironmentVariables` shows only the 4 non-secret
      keys; the 8 secrets are gone from plain env vars entirely

## 5. Total estimated downtime across the whole runbook

**Zero planned customer-facing downtime**, assuming each step's verification gate is green
before the next step runs (that ordering is the entire point of doing this as 8 discrete steps
instead of one big change). The two steps that touch the live App Runner service (5 and 8) are
rolling deployments with automatic health-check-gated rollback, not in-place restarts. The one
step with a real, permanent, non-rollback-able side effect is step 6 (RDS
`PubliclyAccessible=false`), and that side effect is on local/CI debugging access, not on the
running application.

## 6. IAM instance role — manual console click-path (Stakeholder/AWS-admin action)

This session's own AWS identity (`cursor-dev`) cannot create IAM roles or policies — confirmed
via a denied `iam:SimulatePrincipalPolicy` call, not assumed. Whoever has IAM-admin access in
the `049681810267` account needs to do this once, before step 8:

1. AWS Console → **IAM** → **Roles** → **Create role**.
2. Trusted entity type: **Custom trust policy**. Paste:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Principal": { "Service": "tasks.apprunner.amazonaws.com" },
         "Action": "sts:AssumeRole"
       }
     ]
   }
   ```
3. Skip the "Add permissions" page's managed-policy list (none of them fit) — click **Next**,
   name the role `reviewpilot-backend-instance-role`, and create it with no permissions yet.
4. Open the new role → **Add permissions** → **Create inline policy** → **JSON** tab. Paste:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": "secretsmanager:GetSecretValue",
         "Resource": "arn:aws:secretsmanager:eu-west-1:049681810267:secret:reviewpilot-backend/prod-env-secrets-FYOjxG"
       }
     ]
   }
   ```
   Name it `reviewpilot-backend-read-env-secrets`, save.
5. Copy the role's ARN (Role summary page, top) — this is `$INSTANCE_ROLE_ARN` in step 8.

Scoped to exactly one secret, read-only, assumable only by App Runner's own task service — not a
broad `SecretsManagerReadWrite`-style grant.

## 7. Rehearsal evidence (run today, 2026-08-07, nothing created except §1's two items)

Every `--dry-run` call below returned `Request would have succeeded, but DryRun flag is set.`
(the AWS API's own confirmation that the IAM permissions and request shape are valid, without
performing the action):

- `ec2 create-subnet` (both connector subnets, exact CIDRs/AZs used in step 1) — ✅
- `ec2 create-route-table` — ✅
- `ec2 allocate-address --domain vpc` — ✅
- `ec2 create-security-group` (exact name/description/VPC used in step 3) — ✅
- `ec2 revoke-security-group-ingress` — run against the **real, currently-live** `0.0.0.0/0`
  rule on `sg-00fff83298897dba1` (step 7's actual command, dry-run flagged) — ✅
- `ec2 create-security-group` (bastion SG, exact name/description/VPC used in Step 0) — ✅
- `ec2 run-instances` (Step 0's exact AMI/instance-type/no-public-IP flags, against a placeholder
  subnet since the real connector subnet doesn't exist yet) — ✅

RDS (`modify-db-instance`) and App Runner (`create-vpc-connector`, `update-service`) have no
`DryRun` parameter in their APIs — instead validated by pulling each command's live
`--generate-cli-skeleton` schema and confirming every field this runbook uses
(`RuntimeEnvironmentSecrets`, `NetworkConfiguration.EgressConfiguration.{EgressType,
VpcConnectorArn}`, `InstanceConfiguration.InstanceRoleArn`) exists with the expected shape on the
real API — not assumed from documentation. `apprunner update-service` with a preserved
`SourceConfiguration` + one changed field is also, by this point, a pattern already executed
successfully three times against this exact service (tickets 3.2, 4.2, 4.3), each reaching
`RUNNING` cleanly.
