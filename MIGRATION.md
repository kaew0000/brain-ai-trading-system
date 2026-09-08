# MIGRATION — CORS: Deny by Default (V16 §59)

## Do you need to do anything?

**No, in the overwhelming majority of cases.** The bundled dashboard
(production build and Vite dev server) and every existing frontend API
call are same-origin already — see PATCH_NOTES.md for how this was
confirmed. Restart after merging and nothing changes for normal usage.

## When you DO need to do something

Only if you build or connect a genuinely separate browser-based
client that calls this API cross-origin (a different dashboard, a
mobile-web wrapper hosted on its own domain, a third-party
integration's frontend, etc.) — not curl, not a server-to-server
script, not the bundled dashboard. In that case, add its origin:

```bash
# .env
CORS_ALLOWED_ORIGINS=["https://your-other-client.example.com"]
```

Restart after changing this. Multiple origins: a JSON array with more
than one entry, e.g. `["https://a.example.com","https://b.example.com"]`.

## Rollback

Revert this branch and restart — `CORSMiddleware` goes back to
`allow_origins=["*"]`. No data or schema involved; purely a runtime
config change either direction.
