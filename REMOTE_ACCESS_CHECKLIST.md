# Remote Access Checklist (TASK-015)

Goal: allow remote access only through one secure channel (VPN/mesh), with no direct public exposure of dashboard/API.

## 1) Baseline security profile
Verify `.env.prod` values:

- `DASHBOARD_AUTH_ENABLED=1`
- `DASHBOARD_ACCESS_TOKEN=<strong_secret>`
- `DASHBOARD_AUTH_COOKIE_SECURE=1`
- `DASHBOARD_ALLOW_PUBLIC=0`
- `API_DEBUG_EVENTS=0`
- `API_DEBUG_EVENTS_REMOTE=0`
- `DASHBOARD_TRUSTED_NETS=127.0.0.1/32,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10,fc00::/7`

## 2) Remote channel
Pick one channel and keep it as the only remote path:

- mesh VPN (recommended): Tailscale/WireGuard/ZeroTier
- no public port forwarding for port 8000

## 3) Start in prod profile
```bash
python scripts/run_web_service.py --profile prod
```

`run_web_service.py` must reject startup if:
- `DASHBOARD_AUTH_ENABLED=0`
- `DASHBOARD_ALLOW_PUBLIC=1`
- `DASHBOARD_ACCESS_TOKEN` is missing

## 4) Trusted-device verification (via VPN/mesh)
1. Open `/dashboard?token=<DASHBOARD_ACCESS_TOKEN>` and confirm login works.
2. Call `/ops/services` with token and verify:
   - `security.auth_required == true`
   - `security.public_access_allowed == false`
   - `security.debug_events_remote == false`
   - `security.status == "ok"`

## 5) Untrusted-channel verification (outside VPN/mesh)
1. Try `GET /dashboard` and any API endpoint (`/today`, `/tasks`).
2. Expected result: `403` (`Remote access is restricted...`) even with token.

## 6) Debug/events are not exposed outward
1. Ensure `API_DEBUG_EVENTS_REMOTE=0`.
2. From untrusted channel, requests with `debug=1` must not expose `events`.
3. On trusted channel, `events` are available only if `API_DEBUG_EVENTS=1`.

## 7) Final done state
TASK-015 is done when:
- remote access is only through VPN/mesh,
- direct public access is blocked,
- auth is enforced,
- debug/events are not exposed outward,
- `/ops/services` returns `security.status = ok`.
