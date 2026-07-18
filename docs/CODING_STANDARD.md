# Brain Bot V16 Coding Standard

---

# Python Version

Python 3.12+

---

# Formatting

Use Ruff

PEP8

Type hints required

Docstrings required

---

# Naming

Classes

PascalCase

Functions

snake_case

Variables

snake_case

Constants

UPPER_CASE

Private methods

_prefix

---

# Module Rules

One responsibility per module.

No duplicated logic.

Prefer composition over inheritance.

No circular imports.

Dependency Injection preferred.

---

# Logging

Never use print()

Always use logger

Log Levels

DEBUG

INFO

WARNING

ERROR

CRITICAL

---

# Error Handling

Never swallow exceptions.

Always log.

Always provide context.

Avoid bare except.

---

# Testing

Every new module

↓

New tests

Every bug

↓

Regression test

Never reduce coverage.

---

# Documentation

Every module

↓

Docstring

Every API

↓

API.md

Every architecture change

↓

architecture.md

Every release

↓

CHANGELOG.md

---

# Performance

Avoid unnecessary allocations.

Reuse existing services.

Avoid duplicate API calls.

Cache expensive operations.

Avoid blocking I/O.

Prefer async when appropriate.

---

# Security

Never hardcode API keys.

Never commit .env

Never commit databases.

Validate user input.

Escape outputs.

Least privilege.

---

# Git

One feature

↓

One branch

One PR

↓

One logical change

Every commit

↓

Meaningful message

---

# Review Checklist

✓ Tests pass

✓ Ruff clean

✓ Docs updated

✓ Architecture updated

✓ No duplicate code

✓ Backward compatible

✓ Production ready