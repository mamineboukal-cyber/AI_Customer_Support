# MoroccoTech Chat UI (Phase 1) Implementation Plan

> Built inline in one session, task by task (no subagents). Steps use checkbox (`- [ ]`) syntax.
> Approved 2026-11-27 with changes: tagline, fourth fact label, stop after Task 4, phase 2 list.

**Goal:** A React + Vite web chat page in `frontend/` that talks to the existing `POST /chat` and looks like a light, purple/lavender/blue bento grid.

**Architecture:** One page. `App` lays out four bento cards. All chat state lives in one hook, `useChat`, which talks to `api.js` (fetch) and `storage.js` (localStorage). The components only display things and call back. Every visible text lives in `strings.js`.

**Tech Stack:** React 19, Vite (latest), plain CSS with variables, Vitest + jsdom + Testing Library. No TypeScript, no UI library.

**Spec:** the user's message of 2026-11-27 (phase 1 section). Phase 2 is out of scope.

## Facts checked before planning

- Node v24.19.0 and npm 11.17.0: new enough for Vite (needs 20.19+ or 22.12+).
- **`main` has no `app/main.py`**: `/chat` only exists on `feature/api` (c3d42a8), which isn't merged. The worktree branches off `main` as asked and only adds `frontend/`. For the manual run, start FastAPI from the existing `feature/api` checkout (the main folder). The proxy only needs `localhost:8000`.
- Worktrees live in `.worktrees/` (already in `.git/info/exclude`). New one: `.worktrees/chat-ui` on branch `feature/chat-ui`.
- The knowledge base is the same on `main` and `feature/api`. The store facts below are copied from it (stock numbers are left out on purpose, because they change).
- The server's handoff text is `"I don't know. Let me connect you to a human agent."`. **This conflicts with "no live agent"**: it's server text, so phase 1 doesn't change it. The card under it is what states the honest situation. Open question for you (see the end).

## Global Constraints

- All of the work happens in `frontend/` inside worktree `.worktrees/chat-ui` on `feature/chat-ui`, branched from `main`. Never touch the untracked `CLAUDE.md`. No push, no PR, no CI changes.
- No Claude/AI attribution. After every commit, run `git log -1 --format=%B` and amend if needed.
- React + Vite, plain CSS, **no TypeScript, no UI library**. Colors come only from CSS variables in `src/styles/tokens.css`.
- Bot text is rendered as plain text. `dangerouslySetInnerHTML` never appears (checked with a grep in Task 5).
- Every visible text, the bot name, the locale and the direction live in `src/strings.js`. Layout uses logical CSS properties (`margin-inline-*`, `padding-inline-*`, `inset-inline-*`, `text-align: start`), never `left`/`right`, so `dir="rtl"` works later.
- Dev proxy: `/chat` and `/health` go to `http://127.0.0.1:8000`. No CORS change on the server.
- Always store the `session_id` from the **last** response.
- Max message length is 2000 (same as the server). The counter shows from 1800 characters.
- Animations sit inside `@media (prefers-reduced-motion: no-preference)`, or are switched off under `reduce`.
- The reference images are never copied into the repo. The bot icon is an original inline SVG (the reference icon is too low-res). Nothing from the other product's name, avatar or branding is used.

## Review Focus

1. **Bad or unavailable localStorage** (corrupt JSON, old shape, storage blocked in private mode): the page loads with the greeting and doesn't crash. Test in Task 1 (`storage.test.js`).
2. **Server or proxy failure** (FastAPI down, so Vite answers 500/502; a 422; a body that isn't JSON; network error): a friendly error with Retry, never raw text. Retry sends the same message once, without a duplicate customer bubble. Tests in Task 1 (`api.test.js`) and Task 4 (`App.test.jsx`).
3. **Arabic/Darija typing** (customers write it): pressing Enter while an input method is still composing must not send, and bubbles use `dir="auto"` so Arabic shows right-to-left even on an LTR page. Tests in Task 2 and Task 3.
4. **Double send** (Enter pressed twice fast, or a quick question clicked while waiting): only one request goes out. The guard sits in `useChat.send`, not just on the disabled button. Test in Task 4.
5. **"New chat" pressed while a reply is on its way**: the late reply must not show up in the new chat or overwrite its session. Test in Task 4.

---

### Task 1: Worktree, scaffold, strings, storage, API client

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.js`, `frontend/index.html`, `frontend/.gitignore` (`node_modules`, `dist`), `frontend/src/main.jsx`, `frontend/src/test-setup.js`
- Create: `frontend/src/strings.js`, `frontend/src/storage.js`, `frontend/src/api.js`
- Test: `frontend/src/storage.test.js`, `frontend/src/api.test.js`

**Interfaces:**
- Produces:
  - `STRINGS` (default export of `strings.js`), an object with: `botName: "Zelli"`, `locale: "en"`, `dir: "ltr"`, `greeting: "Hi! I'm Zelli, how can I help you today?"`, plus all the copy listed below.
  - `loadChat() -> { sessionId: string|null, messages: Message[] } | null` (null when missing, invalid or unreadable), `saveChat({ sessionId, messages }) -> void` (never throws), `clearChat() -> void` (never throws). Key: `"moroccotech-chat-v1"`.
  - `sendMessage(message: string, sessionId: string|null) -> Promise<{ reply, sessionId, handoff }>`. It throws `ChatError` (exported) on network failure, non-2xx, or a body without a string `reply` and `session_id`. It leaves out `session_id` when it is null.
  - `Message` shape (used by every later task): `{ id: string, role: "user"|"bot"|"handoff"|"error", text: string, time: string (ISO) }`. The `error` role also has `retryText: string`.

- [ ] **Step 1:** `git worktree add .worktrees/chat-ui -b feature/chat-ui main`. Write `package.json` by hand, without the create-vite template, so no template leftovers end up in the repo. Scripts: `dev`, `build`, `preview`, `test: "vitest run"`. `npm install react react-dom` and `npm install -D vite @vitejs/plugin-react vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event`.
- [ ] **Step 2:** `vite.config.js`: react plugin, `server.proxy` for `/chat` and `/health` to `http://127.0.0.1:8000`, `test: { environment: "jsdom", setupFiles: "./src/test-setup.js" }`. `index.html` is `lang="en"`, with a viewport meta and title "MoroccoTech Support".
- [ ] **Step 3: Write the failing tests**
  - `storage.test.js`: a save→load round trip gives back the same object. `localStorage` holding `"{not json"` makes `loadChat()` return null. `{"messages": "x"}` gives null (bad shape). When `setItem` throws (mocked), `saveChat` doesn't throw. `clearChat()` followed by `loadChat()` gives null.
  - `api.test.js` (fetch mocked):
    - It POSTs to `/chat` with the body `{"message":"hi"}` when sessionId is null, and `{"message":"hi","session_id":"abc"}` otherwise.
    - It maps `{reply, session_id, handoff}` to `{reply, sessionId, handoff}`.
    - It throws `ChatError` on: a 500 with a text body, a 422, a body of `"<html>"`, and a rejected fetch.
- [ ] **Step 4:** Run `npm test`. Expected: FAIL (modules missing).
- [ ] **Step 5:** Implement `strings.js`, `storage.js` and `api.js` against the interfaces above.

  Copy in `strings.js`. These are decisions, so use them exactly:
  - `title: "MoroccoTech Support"`, `newChat: "New chat"`, `you: "You"`, `typing: "Typing"`
  - `inputPlaceholder: "Write your message…"`, `send: "Send"`, `counter: (n, max) => \`${n} / ${max}\``
  - `errorText: "Sorry, I couldn't reach our server. Please check your connection and try again."`, `retry: "Retry"`
  - `handoffLine: "Zelli couldn't answer this one"`
  - `handoffTitle: "No live agent in this chat"`
  - `handoffBody: "Nobody from our team is following this chat right now, so you won't get a reply here. You can ask something else or start a new chat."`
  - `botTagline: "MoroccoTech assistant"` (no language list: not verified at scale, and the model will change)
  - `quickTitle: "Quick questions"`, `quickQuestions: ["Is the Mechanical Keyboard K1 in stock?", "How long does delivery to Tangier take?", "Can I pay cash on delivery?", "What is your return policy?"]`
  - `factsTitle: "Good to know"`, `facts`: an array of `{ value, label }`:
    - `"500 MAD"`: "Free shipping above"
    - `"1–2 days"`: "Delivery to Casablanca and Rabat"
    - `"14 days"`: "To return an unused product"
    - `"Cash or card"`: "Cash on delivery all over Morocco, or pay by card"
- [ ] **Step 6:** Run `npm test`. Expected: all storage and api tests PASS.
- [ ] **Step 7:** Commit with `feat(frontend): Vite + React scaffold, strings, storage and API client`, then check `git log -1 --format=%B`.

### Task 2: Message display components

**Files:**
- Create: `frontend/src/components/Message.jsx`, `MessageList.jsx`, `HandoffNotice.jsx`, `ErrorNotice.jsx`, `TypingIndicator.jsx`, `BotIcon.jsx`
- Test: `frontend/src/components/MessageList.test.jsx`, `TypingIndicator.test.jsx`

**Interfaces:**
- Consumes: `STRINGS`, `Message`.
- Produces:
  - `<MessageList messages={Message[]} waiting={bool} onRetry={(errorId) => void} />`: a `role="log"` list that scrolls to the bottom whenever `messages` or `waiting` change. Under it, `<TypingIndicator />` shows while `waiting`.
  - `<Message message />`: a bubble with `dir="auto"` on the text, and a meta line under it with `STRINGS.you` or `STRINGS.botName`, then `·`, then the time formatted with `Intl.DateTimeFormat(STRINGS.locale, { hour: "2-digit", minute: "2-digit" })`.
  - `<HandoffNotice />`: a centered system line plus a card.
  - `<ErrorNotice onRetry />`: the error text plus a Retry button.
  - `<BotIcon size={number} />`: an original SVG robot (round head, antenna, two eyes, smile) in theme colors, with `aria-hidden="true"`.

- [ ] **Step 1: Write the failing tests**
  - `MessageList.test.jsx`:
    - A user message "Hi" and a bot message "Hello" both render. "You" and "Zelli" are both present, and both show a time matching `/\d{2}:\d{2}/`.
    - A bot message `"<b>bold</b>"` is shown literally (`getByText("<b>bold</b>")`, and the container has no `b` element).
    - A `handoff` message shows `STRINGS.handoffLine` and `STRINGS.handoffTitle`.
    - An `error` message shows a "Retry" button, and clicking it calls `onRetry` with that message's id.
    - The bubble text element has `dir="auto"`.
  - `TypingIndicator.test.jsx`: `role="status"` contains "Typing", with exactly 3 dot elements. With `waiting={false}`, MessageList renders no status.
- [ ] **Step 2:** Run `npx vitest run src/components`. Expected: FAIL.
- [ ] **Step 3:** Implement the components above. Use `scrollIntoView` on an end marker for the auto-scroll. jsdom doesn't implement it, so stub `Element.prototype.scrollIntoView` in `test-setup.js`.
- [ ] **Step 4:** Run the tests again. Expected: PASS.
- [ ] **Step 5:** Commit with `feat(frontend): message list, typing indicator, handoff and error notices`, then check the commit message.

### Task 3: Composer (input + send)

**Files:**
- Create: `frontend/src/components/Composer.jsx`
- Test: `frontend/src/components/Composer.test.jsx`

**Interfaces:**
- Produces: `<Composer disabled={bool} onSend={(text) => void} />`. It owns its own textarea text. It calls `onSend(text.trim())` and then clears the field.

- [ ] **Step 1: Write the failing tests**
  - Typing "hello" and pressing Enter calls `onSend("hello")` once and empties the field.
  - Shift+Enter adds a newline and doesn't call `onSend`.
  - Enter with `isComposing: true` doesn't call `onSend`.
  - Whitespace only: the Send button is disabled, and Enter doesn't call `onSend`.
  - `disabled`: the Send button is disabled, and Enter doesn't call `onSend`. The textarea stays editable.
  - The textarea has `maxLength=2000`. No counter shows at 1799 characters; "1800 / 2000" shows at 1800.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement it: an auto-growing textarea (rows 1 to 5, by resetting its height to its `scrollHeight`), and a round icon Send button with an `aria-label` from `STRINGS.send`.
- [ ] **Step 4:** Run it. Expected: PASS.
- [ ] **Step 5:** Commit with `feat(frontend): composer with Enter to send, counter and IME guard`, then check the commit message.

### Task 4: useChat hook, chat card, bento page and styles

**Files:**
- Create: `frontend/src/useChat.js`, `frontend/src/App.jsx`, `frontend/src/components/ChatCard.jsx`, `BotCard.jsx`, `QuickQuestions.jsx`, `StoreFacts.jsx`, `frontend/src/styles/tokens.css`, `frontend/src/styles/app.css`
- Test: `frontend/src/App.test.jsx`

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: `useChat() -> { messages, waiting, send(text), retry(errorId), newChat() }`.
  - Start state: `loadChat()`, or else `{ sessionId: null, messages: [greeting] }`. The greeting is a local bot message and is never sent to the server.
  - `send(text)`: ignored while waiting (use a ref, so two calls in the same tick can't both go through). It appends a user message, sets `waiting`, and calls `sendMessage`. On success it stores `sessionId` from the response and appends a bot message, plus a `handoff` item when `handoff` is true. On `ChatError` it appends an `error` item with `retryText`.
  - `retry(id)`: removes that error item and resends its `retryText` **without** adding a new user bubble.
  - `newChat()`: runs `clearChat()`, resets to the greeting, and increments a "chat generation" counter. A reply that comes back with an older generation is thrown away.
  - Every state change is persisted with `saveChat` (in a `useEffect`). The `waiting` flag isn't persisted.
- Layout: `ChatCard` (header with BotIcon, title and "New chat" button; MessageList; Composer), `BotCard` (big icon, `STRINGS.botName`, tagline), `QuickQuestions` (buttons that call `send`, disabled while waiting), `StoreFacts` (value/label tiles).

- [ ] **Step 1: Write the failing tests** in `App.test.jsx` (fetch mocked, localStorage cleared before each test)
  - First load shows the greeting text exactly.
  - Sending "hi" shows "hi", then "Typing", then the reply. Once the reply is in, "Typing" is gone.
  - **Session:** response 1 returns session `"A"` and response 2 returns `"B"`. The 2nd request carries `"A"` and the 3rd carries `"B"`. After unmounting and remounting, the restored chat shows all the earlier messages, and the next request carries `"B"`.
  - **Retry:** the 1st fetch rejects, so the error text and Retry show. The 2nd fetch resolves. Clicking Retry shows the reply. "hi" appears exactly once, and fetch was called twice.
  - **Handoff:** `handoff: true` shows the reply text, the handoff line and the card.
  - **Double send:** two Enter presses before fetch resolves lead to exactly 1 fetch call. A quick-question button is disabled while waiting.
  - **New chat mid-wait:** send, click "New chat", then resolve fetch. Only the greeting is shown, and the next request has no `session_id`.
  - **Corrupt storage:** `localStorage` holding `"{oops"` makes the page show the greeting.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement `useChat`, the cards and `App`. `App` puts `dir={STRINGS.dir}` and `lang={STRINGS.locale}` on its root.
- [ ] **Step 4:** Styles.
  - `tokens.css`:
    - `--bg #f4f2ff`, `--card #ffffff`, `--lavender #e9e4ff`, `--purple #5b3df5`, `--purple-deep #3a22b8`, `--blue #3b82f6`, `--sky #dbeafe`, `--text #1d1b2f`, `--muted #6b6880`
    - `--user-bubble var(--purple)` (white text), `--bot-bubble #f1efff`, `--radius-card 28px`, `--radius-bubble 20px`
  - `app.css`:
    - Desktop (≥ 900px) grid: `grid-template-columns: 2fr 1fr`. The chat card spans 3 rows, at height `min(820px, calc(100dvh - 48px))`, and only the message list scrolls.
    - The right column holds BotCard (purple gradient, white text), QuickQuestions (lavender) and StoreFacts (sky, 2×2 tiles).
    - Below 900px: one column, chat card first (by DOM order), and the chat card height is `78dvh`.
    - User bubbles use `align-self: flex-end`, bot bubbles `flex-start`. The handoff line is centered with a divider.
    - The send button is a 44px circle.
    - Message appear: fade + 8px rise. The dots bounce. Both live inside `@media (prefers-reduced-motion: no-preference)`.
- [ ] **Step 5:** Run `npm test`. Expected: all suites PASS.
- [ ] **Step 6:** Commit with `feat(frontend): chat state hook and bento page`, then check the commit message.

> **Stop point:** after Task 4, hand over the exact commands to run the page (FastAPI from the `feature/api` checkout, plus `npm run dev`) and wait for the user before Task 5.

### Task 5: Verification and handoff to the user

- [ ] **Step 1:** Check the rules:
  - `grep -rn "dangerouslySetInnerHTML\|left:\|right:\|margin-left\|margin-right\|padding-left\|padding-right" frontend/src`: expected empty.
  - `grep -rn "#[0-9a-fA-F]\{3,6\}" frontend/src --include=*.css`: expected hits only in `tokens.css`.
- [ ] **Step 2:** Run `npm run build`. Expected: success, `dist/` ignored by git.
- [ ] **Step 3:** Live check: uvicorn from the `feature/api` folder on :8000, then `npm run dev` in the worktree.
  - `curl` `/health` and `/chat` **through** the Vite port, to prove the proxy works.
  - Then a request with an invalid session, to see the 422 is turned into the friendly error in the browser path. The friendly-error part is covered only by the unit tests.
- [ ] **Step 4:** Mutation-check three tests:
  - remove the double-send ref guard
  - store the first `sessionId` instead of the last
  - drop the generation check
  
  Each one must make a test fail. Restore from backups.
- [ ] **Step 5:** Report: how to run it, what was verified, and what wasn't (the visual look and mobile layout in a real browser, real screen readers, Safari private mode).

## Open question for you (doesn't block the plan)

The server's handoff reply says "Let me connect you to a human agent", which isn't true without a live agent. Phase 1 leaves it alone (`HANDOFF_MESSAGE` is pinned by the Python tests), and the card under it says plainly that nobody is following the chat. Rewording it server-side would be a small backend change for later.

## Phase 2 (later, not built now)

- `/chat` also returns whether an admin inquiry was raised.
- A new-messages endpoint, so the admin's answer shows up on the page. Until it exists, the admin's answer is stored in the database but the page can't fetch it.
- FastAPI serves the built frontend.
- `ERROR_MESSAGE` also says "human agent" and shows as a normal bubble, without the handoff card. The API should return an explicit handoff/error signal, and neither `HANDOFF_MESSAGE` nor `ERROR_MESSAGE` should promise a human any more.
