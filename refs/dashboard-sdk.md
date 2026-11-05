# Dashboard Plugin SDK — reference (from NousResearch/hermes-example-plugins)

## manifest.json (example)
```json
{
  "name": "example",
  "label": "Example",
  "description": "...",
  "icon": "Package",
  "version": "1.0.0",
  "tab": { "path": "/example", "position": "after:skills" },
  "entry": "dist/index.js",
  "css": "dist/style.css",
  "api": "plugin_api.py"
}
```
Icon = lucide icon name. `position` supports `after:<tab>` / `before:<tab>`.

## Bundle contract (dist/index.js — plain IIFE, NO build step, NO imports)
```js
(function () {
  "use strict";
  const SDK = window.__HERMES_PLUGIN_SDK__;
  const { React } = SDK;
  const { Card, CardHeader, CardTitle, CardContent, Badge, Button, Input, Label,
          Select, Separator, Tabs } = SDK.components;   // shadcn set
  const { useState, useEffect, useCallback, useMemo, useRef } = SDK.hooks;
  const { cn, timeAgo, isoTimeAgo } = SDK.utils;
  // SDK.fetchJSON(path) → JSON (handles dashboard auth)
  // SDK.api → Hermes API client (getStatus(), getSessions(), ...)

  function MyPage() { /* React.createElement only — no JSX */ }

  window.__HERMES_PLUGINS__.register("example", MyPage);
  // optional slot: window.__HERMES_PLUGINS__.registerSlot("example", "sessions:top", Comp);
})();
```
- Tailwind classes available (theme-aware: `text-muted-foreground`, `bg-background/40`, `border-border`, `font-courier`).
- `SDK.fetchJSON("/api/plugins/example/hello")` for backend calls.
- Registration name must match manifest `name`.

## plugin_api.py
```python
from fastapi import APIRouter
router = APIRouter()   # mounted at /api/plugins/<name>/
@router.get("/hello")
async def hello(): return {"message": "hi"}
```

## Install/rescan
Copy dir into `~/.hermes/plugins/<name>/` (must contain `dashboard/manifest.json`), then restart dashboard or `GET /api/dashboard/plugins/rescan`.
