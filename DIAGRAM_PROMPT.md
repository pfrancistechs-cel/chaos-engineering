# Diagram prompt (copy everything below into an image-generation model)

Create a clean, professional cloud infrastructure diagram, 16:9 landscape, white background, flat vector style, large readable labels, thin dark-grey lines, soft pastel fills. Title at the top: "Chaos Engineering: break it on purpose, then prove it recovers (one EC2 instance)".

LAYOUT, left to right.

LEFT: a "Browser (your laptop)" box listing two items: "Chaos console :8081 (live green/red bars)" and "Shop checkout :8080". Solid arrows labeled "HTTP" go to the right. Below it a "Terminal (SSH port 22)" box with a dashed arrow to the right.

MIDDLE: a thin firewall icon labeled "Security group: inbound TCP 22, 8080, 8081, all from my IP only; outbound all".

RIGHT: a large AWS-orange-bordered box labeled "AWS Region > Default VPC > EC2 instance m7i-flex.large (Ubuntu 24.04, 2 vCPU, 8 GiB)". Inside it, one big blue rounded box labeled "Docker Engine > Docker network 172.29.0.0/24 (6 containers)". Inside it, left to right:
1. A green box "gateway (nginx) :8080" with the note "round robin, retry on the other replica, 2.5 s timeout".
2. Two green boxes stacked: "shop1 172.29.0.11" and "shop2 172.29.0.12". A small switch icon on each labeled "mode: naive or hardened (config/mode file)". A note under them: "hardened = 0.3 s timeout, 1 retry, circuit breaker, last-known-stock fallback".
3. An orange box "chaos proxy (fault injector)" with three small tags: "latency", "errors", "hang", and a small port label "control 127.0.0.1:9002".
4. A purple box "inventory (the dependency)".
5. A blue box "chaos console :8081" with a live bar chart icon, and a small box "results/last.json".
6. On the terminal side, a red box "chaos runner (scripts/chaos.py)" containing five numbered steps: "1 measure steady state", "2 hypothesis", "3 inject fault (guardrail aborts if almost everything fails)", "4 verdict HELD or REFUTED", "5 remove fault, check recovery".

Numbered arrows, each with a short label:
1. Browser to gateway: "checkout requests".
2. Gateway to shop1 and shop2: "load balance".
3. Shops to chaos proxy to inventory: "stock lookup".
4. Console to gateway: "5 probes per second".
5. Runner to chaos proxy: "set delay, errors or hang" (red dashed).
6. Runner to the Docker daemon: "docker kill / pause shop1, docker stop inventory" (red dashed), with a curved arrow "Docker restarts the killed replica".
7. Runner to results/last.json: "verdict".

Add a small legend: green = service, orange = fault injection, purple = dependency, blue = observation, red = experiment control. Add a footer note: "Everything runs as Docker containers on this one instance. No other AWS services are used."

Do not add any AWS services (no CloudWatch, SNS, ALB, IAM, Fault Injection Service). Use generic icons, with a simple Docker whale and the nginx logo as the only logos. Make sure all text is spelled exactly as written above.
