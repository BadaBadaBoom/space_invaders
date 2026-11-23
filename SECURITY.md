# Security Policy

## Reporting a vulnerability

Please do **not** open a public issue for a security problem, and do not
include exploit details in a public comment.

Use GitHub's private vulnerability reporting form:

https://github.com/BadaBadaBoom/space_invaders/security/advisories/new

If that form is unavailable, open a minimal public issue asking for a private
contact channel, without describing the vulnerability or how to reproduce it.

## Scope

This is a local desktop pygame game. Relevant reports include:

- arbitrary code execution or unsafe file handling caused by this project;
- crashes or memory-safety problems in the Python code;
- unsafe handling of downloaded NASA pages or images;
- inadvertent exposure of local data or credentials.

Third-party dependencies such as pygame-ce and numpy are maintained by their
own projects; report their issues upstream.

## Supported versions

Security fixes target the current `main` branch. Older development branches
may be behind `main` and are not separately supported.
