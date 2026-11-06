# STEPS: Chaos Engineering

## Prerequisites (set these up BEFORE step 1)

| Need | Details |
|---|---|
| **AWS account** | Any account that can launch EC2. No IAM role, no other AWS service. Use one region for everything below. |
| **Instance type** | `m7i-flex.large` (2 vCPU, 8 GiB). This project needs under 1 GiB. |
| **OS image (AMI)** | Ubuntu Server 24.04 LTS (64-bit x86). 22.04 also works. |
| **Disk** | 20 GiB gp3. |
| **Key pair** | An RSA `.pem` key pair created in EC2 (step 0a). |
| **Security group** | Created in step 0b. **Inbound: exactly three rules, all with source My IP: SSH TCP 22; Custom TCP 8080 (the shop); Custom TCP 8081 (chaos console).** **Outbound: leave the default (All traffic, 0.0.0.0/0)**, because the instance must reach Docker Hub (images) and Docker's apt repo. |
| **Code on the instance** | Option A: private GitHub repo plus a fine-grained token (Contents: Read) used as the password for `git clone`. Option B: copy the zip with `scp` (step 2). |
| **Accounts / tokens** | None. |
| **On your laptop** | A terminal with `ssh`/`scp` and a web browser. **No SSH tunnel is needed:** open `http://<PUBLIC-IP>:8081/` directly. |

**Time:** about 15 minutes of setup (the first start builds one small image and pulls two; preflight includes the tests), about 8 minutes for the full game day. **Cost:** about $0.10/hour at your quoted rate, plus pennies for the disk. Do step 11 when finished.

---

## Step 0: Create the key pair, security group and instance (AWS console)

**0a. Key pair.** EC2 > Network & Security > Key pairs > **Create key pair**. Name `chaos-lab-key`, type **RSA**, format **.pem**. The file downloads once; keep it safe. On your laptop, lock down its permissions:

```bash
# Linux / macOS
chmod 400 ~/Downloads/chaos-lab-key.pem
```
```powershell
# Windows PowerShell (OpenSSH)
icacls "$HOME\Downloads\chaos-lab-key.pem" /inheritance:r /grant:r "$($env:USERNAME):(R)"
```

**0b. Security group.** EC2 > Network & Security > Security Groups > **Create security group**.
- Name: `chaos-lab-sg`, Description: `SSH and chaos demo pages from my IP`, VPC: the default VPC.
- **Inbound rules > Add rule** (three times; Type `SSH` for the first, `Custom TCP` for the rest; Protocol `TCP`; **Source `My IP`** every time):
  1. Port range `22` (SSH)
  2. Port range `8080` (the shop)
  3. Port range `8081` (chaos console)
- **Outbound rules:** leave the default rule (Type `All traffic`, Destination `0.0.0.0/0`).
- Click **Create security group**.

> Showing the demo to someone on a different network? Their browser is blocked by "My IP". Either share your screen, or add their public IP followed by `/32` as the source of the 8081 rule. Do not use `0.0.0.0/0`.

**0c. Launch the instance.** EC2 > Instances > **Launch instances**.
- Name: `chaos-lab-box`
- Application and OS Image: **Ubuntu**, choose **Ubuntu Server 24.04 LTS**, architecture **64-bit (x86)**
- Instance type: `m7i-flex.large`
- Key pair: `chaos-lab-key`
- Network settings > **Edit**: Auto-assign public IP **Enable**; Firewall: **Select existing security group** > `chaos-lab-sg`
- Configure storage: **20 GiB**, `gp3`
- Advanced details > IAM instance profile: leave as **No IAM role**
- Click **Launch instance**, wait until Instance state is `Running` and Status check is `2/2 passed`, then copy the **Public IPv4 address**. This is your `<PUBLIC-IP>` below.

> If your network changes later, SSH and the pages will time out because "My IP" no longer matches. Edit **all three** inbound rules of `chaos-lab-sg` and set Source to My IP again. Stopping and starting the instance also gives it a new public IP.

## Step 1: Connect to the instance (from your laptop)

```bash
ssh -i ~/Downloads/chaos-lab-key.pem ubuntu@<PUBLIC-IP>
```
Type `yes` at the fingerprint prompt. Every command from here to step 10 runs **on the instance**.

## Step 2: Update packages and get the code

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git unzip
```

**Option A (private GitHub repo):**
```bash
git clone https://github.com/<you>/chaos-engineering.git
cd chaos-engineering
```
When asked, username = your GitHub username, password = the fine-grained token.

**Option B (no GitHub), run from your laptop in the folder holding the zip, then continue on the instance:**
```bash
# on your laptop
scp -i ~/Downloads/chaos-lab-key.pem chaos-engineering.zip ubuntu@<PUBLIC-IP>:~
# on the instance
unzip chaos-engineering.zip
cd chaos-engineering
```

## Step 3: Make the scripts executable (do not skip)

Files that were zipped, uploaded to GitHub or copied between systems often lose their "executable" flag. Without this you get `Permission denied`.

```bash
chmod +x scripts/*.sh scripts/chaos.py
ls -l scripts/        # every .sh line should start with -rwxr-xr-x
```

## Step 4: Install Docker

```bash
./scripts/setup.sh
```
It runs `apt update`/`upgrade`, installs the basic tools and python3, installs Docker Engine and Compose v2 from Docker's official repo (falling back to Ubuntu's `docker.io` package), starts Docker and prints the versions. Takes 3-5 minutes. It ends with `Setup complete.`

## Step 5: Preflight (run this well before the demo)

```bash
./scripts/preflight.sh
```
Checks Docker, disk, memory, ports 8080/8081/9002 and Docker Hub; pulls the images; **starts the whole stack**; runs `smoke.sh`; runs two real experiments (slow dependency against the naive shop must be REFUTED, against the hardened shop must be HELD, about a minute each); and runs the unit tests. Every line must say `ok`, and the last line is `Preflight passed. The naive shop breaks, the hardened shop holds.` First run takes 12-15 minutes (the unit tests take about 7 of them).

## Step 6: Start the stack

```bash
./scripts/up.sh
```
Starts the 6 containers (a no-op if preflight left them running), waits until a checkout works, and prints:

```
Chaos console : http://<PUBLIC-IP>:8081/
The shop      : http://<PUBLIC-IP>:8080/checkout
```

## Step 7: Health check

```bash
./scripts/smoke.sh
```
Every line says `ok` and it ends with **`All 13 checks passed.`**

## Step 8: Open the pages in your browser (on your laptop)

- `http://<PUBLIC-IP>:8081/`: the chaos console. All bars green, mode `naive`, no faults. **Keep this tab open and visible.**
- `http://<PUBLIC-IP>:8080/checkout`: refresh a few times; `"shop"` alternates between `shop1` and `shop2`.

## Step 9: Run the game day (on the instance)

```bash
./scripts/demo.sh gameday          # steady, kill, freeze, naive, hardened: about 8 minutes
```
Or one at a time:
```bash
./scripts/demo.sh steady           # what "healthy" means before we break anything
./scripts/demo.sh kill             # a replica is killed: HELD, Docker restarts it
./scripts/demo.sh freeze           # a replica freezes: no errors but a slow spell (p95 about 2.5 s), HELD
./scripts/demo.sh naive            # four dependency failures vs the first-draft shop: all REFUTED (expected)
./scripts/demo.sh hardened         # the same four failures vs the hardened shop: all HELD
```
Each scenario ends with a green `PASS` (for `naive`, PASS means every experiment was refuted, as expected). Watch the console bars turn red in the naive scenario and stay green in the hardened one.

Run your own experiment:
```bash
./scripts/chaos.sh list
./scripts/chaos.sh run dep-flaky --mode naive
./scripts/chaos.sh run dep-flaky --mode hardened
./scripts/chaos.sh mode hardened   # switch the shop yourself, then break things by hand
curl "http://localhost:9002/set?latency_ms=1500"    # a manual fault; undo with /clear
./scripts/chaos.sh reset           # remove every fault, restart anything stopped
```

## Step 10: Unit tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```
Ends with `OK` (about 7 minutes). They run the shop, the fault proxy, the runner and the real scripts against a local copy of the stack (real nginx, stub `docker`). Preflight already runs them.

## Step 11: Clean up, then terminate the instance

```bash
./scripts/destroy.sh
```
Then in the AWS console: EC2 > Instances > select `chaos-lab-box` > **Instance state > Terminate instance**. Optionally delete the `chaos-lab-sg` security group and `chaos-lab-key` key pair too.

---

## What you should see

| Step | Result |
|---|---|
| 5 | All `ok`, then `Preflight passed.` |
| 6 | Two URLs containing your public IP |
| 7 | `All 13 checks passed.` |
| 8 | Console: green bars, mode `naive`, no faults |
| 9 | Five `PASS` lines, then `ALL SCENARIOS PASSED`. Each experiment prints a table: baseline, fault, recovery |
| 10 | Tests end with `OK` |

## Risky dependencies and fallbacks

| Dependency | Risk | Fallback |
|---|---|---|
| Docker Hub (`nginx`, `python`) | Rate limit or a withdrawn tag | `sudo docker login` with a free account, or change `NGINX_IMAGE` in `.env` and re-run preflight |
| Fixed container IPs (172.29.0.0/24) | Subnet clashes with another Docker network | `sudo docker network ls`; remove the old network or change the subnet in `docker-compose.yml` and `gateway/default.conf` |
| `docker kill` restart | Restart relies on `restart: unless-stopped`; the runner also starts the replica itself | If a replica stays down: `./scripts/chaos.sh reset` |
| Timing | The verdicts depend on timeouts (0.3 s, 2.5 s). A very busy instance can blur them | Do not run other heavy things during the demo; re-run the one experiment |
| Instance busy | Slow answers can fail the steady-state check (exit code 2, nothing injected) | Wait a minute and run again |
| Do not run `destroy.sh` before the demo | It deletes the stack | Re-run preflight afterwards |
| MinIO, LocalStack | **Not used** | none needed |

## If something goes wrong

| Symptom | Fix |
|---|---|
| SSH: `Connection timed out` | Your IP changed. Edit security group `chaos-lab-sg`, inbound rule SSH port 22, Source My IP. Confirm the instance is Running with a public IP. |
| Console never loads | (1) Use `http://` and port 8081. (2) Each port needs its own inbound rule with Source My IP. (3) Check the instance's current public IP. (4) On the instance: `curl -i http://localhost:8081/healthz` should return `200`; if so, it is the security group. |
| Testing the public IP from the instance itself hangs | Expected: the security group only allows your laptop's IP. Use `localhost` on the instance. |
| SSH: `Permission denied (publickey)` | Use user `ubuntu`, the right `.pem`, and `chmod 400` on it. |
| `./scripts/x.sh: Permission denied` | `chmod +x scripts/*.sh scripts/chaos.py` (step 3). Or run with `bash scripts/x.sh`. |
| `bad interpreter: /usr/bin/env bash^M` | Windows line endings. Run `sed -i 's/\r$//' scripts/*.sh` |
| Preflight: `Docker Hub reachable` or a pull fails | Check the outbound rule is All traffic; `sudo docker login`; try again in a minute. |
| Preflight: `Port NNNN is free` fails | `sudo ss -ltnp \| grep ':8080 '`, stop what uses it, or `./scripts/destroy.sh` if it is an old run of this project. |
| `up.sh`: `Checkouts fail` | `sudo docker compose ps`; `sudo docker logs --tail 30 chaos-shop1`. Often the mode file: `cat config/mode` must say `naive` or `hardened`. |
| `smoke.sh`: `all 6 containers are running` fails | `sudo docker compose ps -a` shows which one exited; `sudo docker compose up -d` |
| `smoke.sh`: `no fault is switched on` fails | A previous experiment was interrupted: `./scripts/chaos.sh reset` |
| `chaos.sh run`: exit code 2, "not in steady state" | Working as designed: nothing was injected because the system was already unhealthy. `./scripts/chaos.sh reset`, wait 20 seconds, run again. |
| Exit code 3, "not back to steady state" | The fault is off but the system has not recovered yet. `./scripts/chaos.sh reset` and look at `sudo docker compose ps`. |
| Shop stays `degraded` after an experiment | The breaker re-closes within 5 seconds of the dependency answering. `./scripts/chaos.sh reset` and refresh. |
| `demo.sh`: `The stack is not running` | `./scripts/up.sh` |
| Disk full | `sudo docker system prune -af` (this removes cached images; preflight pulls them again) |
