# ttydiff — Task Breakdown & Dependencies (2-Day Plan)

**How to read this:** every task has an ID, an owner, what it needs to already exist (**Depends On**), and what can't start until it's done (**Blocks**). Work down each person's lane in order — don't jump ahead of a dependency, and don't let a "blocks everyone" task slip.

---

## 0. The One Task Everyone Does First

| ID | Task | Owner | Depends On | Blocks | Time |
|---|---|---|---|---|---|
| **T0** | Lock the data contract: shape of parser events, screen grid state, diff output, and how CLI calls the runner | **All 3, together** | Nothing | **Everything else** | Day 1, first hour |

Nobody starts coding until T0 is agreed. This is the single biggest risk in the whole project — if Siddhesh, Sarvesh, and Shubham each guess at these shapes separately, Day 1 evening's integration fails and you lose Day 2 fixing plumbing instead of features. **This is non-negotiable as the first hour of Day 1.**

---

## 1. Siddhesh's Lane — Parser & Screen (the critical path)

| ID | Task | Depends On | Blocks | Cut if behind? |
|---|---|---|---|---|
| **T2** | Parser core: byte scanner, cursor movement codes, plain character printing, byte-offset/line-col tracking | T0 | T2b, Integration A | No — this is the minimum viable parser |
| **T2b** | Parser: erase codes (`ED`/`EL`) + color codes (SGR) | T2 | T3 (needs these event types), Integration A | Erase codes: keep. Color codes: cuttable if desperate |
| **T3** | Virtual screen grid: consumes parser events, tracks cursor position + cell contents | T2 (can start against T2's early stub events, extend once T2b lands) | Integration A, T4 | No — this is the whole point of the project |

**Why this is the critical path:** Sarvesh's and Shubham's work can proceed in parallel without waiting on Siddhesh, but Integration A (Day 1 evening) cannot happen until T3 is done. If this lane slips, the whole timeline slips. Siddhesh should get help from whoever finishes their own lane early.

---

## 2. Sarvesh's Lane — Runner & Diff Engine

| ID | Task | Depends On | Blocks | Cut if behind? |
|---|---|---|---|---|
| **T1** | PTY runner: spawn one command with a real pseudo-terminal, capture raw output | T0 | T1b, Integration A | No — foundational |
| **T1b** | Extend runner to accept a list of commands, run them strictly one after another | T1 | Integration A (full), T7 | No, but timeout/Ctrl+C-to-skip handling inside it is cuttable |
| **T4** | Diff engine: basic cell-by-cell comparison between two screen states | T0 (state shape agreed) — can build against a **mocked** screen state, doesn't need to wait for T3 to be finished | Integration B | Scroll-detection specifically is cuttable (see note) |

**Note on T4:** Sarvesh does not need to wait for Siddhesh to finish T3 — build the diff engine against a fake/mocked screen state that matches the T0 contract, then swap in the real one at Integration B. This is what lets Sarvesh's lane run in parallel instead of idling.

---

## 3. Shubham's Lane — CLI, Integration, Docs

| ID | Task | Depends On | Blocks | Cut if behind? |
|---|---|---|---|---|
| **T5** | CLI skeleton: `argparse` setup, `run` subcommand accepting multiple command strings | T0 | T6a | No |
| **T6a** | Wire CLI to runner for a single command | T5, T1 | Integration A | No |
| **T7** | Wire CLI to run multiple commands sequentially, printing a diff after each | Integration B, T1b | Demo readiness | No — this is the headline feature |
| **T9** | README + STDLIB.md | Ongoing (draft early, finalize once scope cuts are known) | Submission | No |

---

## 4. Integration Checkpoints (the load-bearing moments)

| ID | Task | Owner | Depends On | Blocks |
|---|---|---|---|---|
| **Integration A** | Runner → Parser → Screen working end-to-end for ONE real command | All 3 | T1b, T2b, T3, T6a | Integration B, all of Day 2 |
| **Integration B** | Screen states → Diff engine → readable output, wired into the pipeline | All 3 | Integration A, T4 | T7, T8 |

**Integration A must happen Day 1 evening — not Day 2.** With only 2 days, there is no slack left to discover interface mismatches on the final day. If Integration A isn't ready by Day 1 evening, that's the signal to start cutting scope immediately (see cut list below), not to push through with the full feature set.

---

## 5. Testing, Demo, Submission

| ID | Task | Owner | Depends On | Blocks |
|---|---|---|---|---|
| **T8** | Test corpus (5-6 fixtures) + `unittest` subtests | Shubham leads, all contribute | Parser-only tests can start once T2b lands (Day 1 evening); end-to-end tests need Integration A/B | Confidence, not a hard blocker |
| **T10** | Full run-through as a judge would do it + record demo | All 3 | T7, T8, T9 | Submission |
| **T11** | Submit: repo, README, STDLIB.md, tests/, build command, deps-proof.txt, video | Shubham | T10 | — |

---

## 6. Dependency Chain — Visual

```
                         ┌─────────────────────────┐
                         │  T0 — Data Contract      │   (All 3, first hour)
                         └───────────┬─────────────┘
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
     Siddhesh's lane        Sarvesh's lane         Shubham's lane
     ┌─────────────┐       ┌─────────────┐        ┌─────────────┐
     │ T2  Parser   │       │ T1  Runner   │        │ T5  CLI      │
     └──────┬──────┘       │   (1 cmd)    │        │  skeleton    │
            ▼               └──────┬──────┘        └──────┬──────┘
     ┌─────────────┐               ▼                      ▼
     │ T2b Erase +  │       ┌─────────────┐        ┌─────────────┐
     │  color codes │       │ T1b Runner   │        │ T6a CLI +    │
     └──────┬──────┘       │ (multi-cmd)  │        │  runner (1)  │
            ▼               └──────┬──────┘        └──────┬──────┘
     ┌─────────────┐               │                       │
     │ T3  Virtual  │               │  (T4 built in         │
     │   Screen     │               │   parallel, mocked    │
     └──────┬──────┘               │   screen state)        │
            │         ┌─────────────┴──────┐                │
            └────────►│                    │◄───────────────┘
                       ▼                    ▼
              ┌─────────────────────────────────┐
              │     INTEGRATION A (Day 1 PM)     │  ← must land Day 1 evening
              │  Runner → Parser → Screen, 1 cmd  │
              └────────────────┬─────────────────┘
                                ▼
                       ┌───────────────┐
                       │  T4  Diff      │  (real screen state swapped in)
                       │   engine       │
                       └───────┬───────┘
                                ▼
              ┌─────────────────────────────────┐
              │     INTEGRATION B (Day 2 AM)     │
              │  Screen states → Diff → output    │
              └────────────────┬─────────────────┘
                                ▼
                       ┌───────────────┐
                       │  T7  CLI:      │
                       │  multi-command  │
                       │  + diff output  │
                       └───────┬───────┘
                                ▼
                       ┌───────────────┐
                       │  T8  Tests     │
                       └───────┬───────┘
                                ▼
                       ┌───────────────┐
                       │ T10 Demo run   │
                       └───────┬───────┘
                                ▼
                       ┌───────────────┐
                       │  T11 Submit    │
                       └───────────────┘
```

---

## 7. If You Fall Behind — Cut in This Order

1. Scroll-region detection in the diff engine (treat a scroll as "everything changed" — correct, just less elegant)
2. Ctrl+C-to-skip / timeout handling in the runner (let commands run to completion instead)
3. SGR color code support in the parser (T2b's color half — keep erase codes, drop color)
4. Chasing 10 STDLIB.md substitutions for the bonus — 6-7 honest ones is fine
5. Anything not already in this plan (no new features once Integration A is behind schedule)

**Never cut:** the data contract step (T0), Integration A, or the honest-limitations section of the README — those are what keep the whole thing from collapsing or getting penalized on Zero-Dependency Craft.
