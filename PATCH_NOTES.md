# PATCH NOTES — World chat & meetings (V16 §83)

Branch: `feat/world-chat-meeting-s83`
Base: `main` @ `7506ac7` (PR #121 merged)
Commit: `feat(world): World chat and meetings (V16 §83)` (exactly one)

## Root cause (verified in code)
1. The World was a read-only viewer by design (`world/docs/architecture.md`): no route accepted chat, and no store existed for
   messages or meeting state.
2. There is no LLM/agent-conversation infrastructure in the repo (only `brain_strategy_intelligence` research providers), so
   NPC replies had to be derived from real state or not exist.
3. Separate from this feature: the 401s seen in the browser console hit every endpoint (not only `/api/world/*`), i.e. the
   session had no Bearer token (not logged in, or `API_KEYS` empty so a new ephemeral key is generated at each restart).
   The §81/§82 code already attaches the token; nothing in World needed changing for that.

## Changes
- Backend: `world/chat/{models,store,responder,meeting,api}.py` (new), `api/world_chat_api.py` (new), `api/app.py`
  (router + shutdown hook), `config/settings.py` (8 settings), `.gitignore` (chat.json).
- Frontend: `pages/world/chatApi.ts`, `components/{StudioView,ChatPanel,MeetingPanel,KanbanPanel}.tsx` (new),
  `WorldPage.tsx` (new default `Studio` tab).
- Docs: `docs/architecture.md` §83, `world/docs/architecture.md` (boundary note), `CHANGELOG.md`, this file, `MIGRATION.md`.

## Verification (actually executed)
See the status report delivered with the bundle (exact counts).

## Limitations / follow-up
- NPC text is templated from real fields; it is not conversation. A real LLM backend would be a separate, explicit decision.
- No Cron panel: no verified read-only scheduler endpoint exists to back it. No multi-player/presence count either.
- Chat/meeting endpoints are VIEWER-level like every other `/api/world/*` route (they cannot affect trading).
- Auto meetings are paced by a single in-process asyncio task; a restart marks a live meeting `stopped`.
- The visual match to the reference screenshots is approximate (Phaser office scene + panels); not checked in a real browser.
