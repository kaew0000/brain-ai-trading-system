# Brain Bot Development Playbook

---

## Workflow

Every feature follows

Design

↓

Architecture Review

↓

Implementation

↓

Unit Tests

↓

Integration Tests

↓

Documentation

↓

Merge

---

## Before Coding

Read

architecture.md

ROADMAP.md

CLAUDE.md

ARCHITECTURE_DECISIONS.md

MODULE_INDEX.md

Never code blindly.

---

## Adding Features

1.

Inspect existing implementation.

2.

Search duplicate functionality.

3.

Design additive changes.

4.

Implement.

5.

Write tests.

6.

Update docs.

---

## Bug Fix

Find root cause.

Never patch symptoms.

Write regression test first.

Fix.

Run all tests.

---

## Refactoring

Allowed only if

No API changes.

No behavior changes.

Coverage maintained.

---

## New Modules

Must contain

Type hints

Docstrings

Tests

Logging

Configuration

Documentation

---

## Pull Request Checklist

✓ Ruff clean

✓ Tests pass

✓ Docs updated

✓ Architecture updated

✓ No duplicated logic

✓ No dead code

✓ No secrets

✓ Backwards compatible

---

## Release Checklist

Run

pytest

ruff

vulture

mypy

Verify

Dashboard

Scanner

Execution

Risk

Portfolio

Journal

Create

CHANGELOG

Version Tag

Release Notes

---

## Long-term Roadmap

Completed

Fix1

Fix2

Dashboard Auth

Risk V2

Scanner

Ranker

Current

Portfolio Manager

Capital Allocation

Correlation Engine

Sector Engine

Upcoming

Execution Scheduler

Portfolio Dashboard

Adaptive AI

Learning Engine

Self Optimization

Auto Strategy Evolution

Autonomous Trading System

---

## Engineering Principles

Keep modules small.

Keep interfaces stable.

Keep logic testable.

Keep documentation current.

Never sacrifice reliability for speed.

Capital protection is always higher priority than profit generation.