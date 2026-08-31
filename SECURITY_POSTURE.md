# InnerLight Security Posture — ransomware-crew threat model
(Assessed against Qilin/S1242-class RaaS playbooks, Aug 2026. Living document.)

## Why most of their playbook cannot land here
Their TTPs target corporate Windows estates: Active Directory lateral
movement (PsExec, GPO tasks, Mimikatz/LSASS), ESXi/vCenter cluster
encryption, volume-shadow deletion, RDP/Citrix exploitation. InnerLight is
one Flask app in a managed Linux container (Render): no AD, no SMB, no RDP,
no Citrix, no VMware, no Windows in production.

## Why the recovery + extortion story favors us
- Stateless app, redeployable from GitHub in minutes — encryption-for-impact
  has almost nothing durable to take hostage
- Code-protected conversations are encrypted per person; a stolen database
  is unreadable — the leak-extortion play is gutted
- The web shield (honeypots, lockouts, rate caps, evidence log) absorbs the
  commodity scanning that precedes these crews

## Where the REAL door is: the founder's endpoint and accounts
Qilin's documented entry is spearphishing (including phishing an MSP
admin's remote-management tool to reach everyone downstream). For
InnerLight, the equivalent single point is the founder's own devices and
accounts. Standing founder actions:
1. Passkeys or app-based 2FA on EMAIL first, then GitHub and Render
2. Treat unexpected attachments and urgent login links as hostile
3. Keep the working PC patched; no cracked software on it, ever
4. Rotate the GitHub access token on a schedule
5. Strong, unique ADMIN_KEY; never reuse it anywhere

## Supply chain
requirements.txt is pinned to the exact versions currently serving. Bumps
are deliberate, reviewed, and go through the verified-deploy gate.
