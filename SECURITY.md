# Security Policy

OpenVision Glass is intended to be developed in public without exposing private deployment details.

## Do Not Commit

- API keys, including OpenAI keys.
- Tailscale hostnames, tailnet IPs, private LAN IPs, or real deployment URLs.
- SSH keys, certificates, keystores, and service tokens.
- Local backend config under `rokidjetson/backend_mvp/config/`.
- Generated logs, runtime streams, build outputs, and local artifacts.

Use environment variables or ignored local config files for deployment-specific values.

## Network Posture

The Jetson backend is designed for trusted LAN/VPN access. Do not expose the backend directly to the public internet without authentication, TLS termination, rate limits, and a full security review.

## Reporting

If you find a security issue, please open a GitHub issue with a minimal description that does not include secrets. For sensitive details, contact the maintainer privately first.
