## Root Cause

Deploy `c9f2a1d` to `auth-proxy` at 14:02Z triggered an error spike peaking at 24.5% at 14:10Z. Rollback `d4e5f6a` at 14:12Z restored error rates to 0.3% by 14:15Z.

## Action Items

- Add canary error-rate gate before full `auth-proxy` rollout.
- Automate rollback trigger when 5xx rate exceeds 5.0%.
