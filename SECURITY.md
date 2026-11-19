# Security

Teddy Manager is designed for a **trusted home network only**. It has no user accounts; the optional 4-digit PIN only
protects against children, not attackers. Do not expose it to the internet.

The import endpoint `/api/import` is protected by a random token (shown in the settings, regenerable).

Please report security issues privately via GitHub's “Report a vulnerability” instead of a public issue.
