# whatsapp-mcp

MCP server for WhatsApp — search contacts, read chats and messages, download
media, and (opt-in) send text, files and voice notes, over stdio. A hardened
rewrite of [lharries/whatsapp-mcp](https://github.com/lharries/whatsapp-mcp)
that drops the upstream Go bridge + HTTP API: the WhatsApp Web protocol runs
in-process through [neonize](https://github.com/Neonize/neonize), a Python
wrapper around [whatsmeow](https://github.com/tulir/whatsmeow), loaded via
ctypes in the same process as the MCP server. One image, one process.

Read-only by default: without `allow_send`, the send tools are not even
registered.

> **Non-obvious:** `whatsapp-mcp login` must be run once, interactively
> (`docker run -it`), against the same `/data` volume the server later uses.
> A fresh volume has no session, so `serve` alone cannot read anything and
> `whatsapp_check_connection` reports `logged_in: false`.

## Config

Copy `config.example.json` and mount it read-only into the container at
`/config/config.json`:

```json
{
  "data_dir": "/data",
  "media_dir": "/media",
  "allow_send": false,
  "allowed_recipients": [],
  "max_media_bytes": 67108864
}
```

- `allow_send` — register the send tools (default `false`).
- `allowed_recipients` — digits-only phone numbers (6–15 digits) or JIDs. Empty
  means any recipient, once `allow_send` is on. Set it.
- `media_dir` — the only place outgoing files may come from. Mount it read-only.
- `max_media_bytes` — size cap for sent and downloaded media (default 64 MiB).
- Unknown keys or wrong types are rejected with a clear error. Set
  `WHATSAPP_MCP_CONFIG` to read a different path.

The app writes with `umask 077`: the session and message history live in the
`/data` volume (named volume `whatsapp-data`; dirs `0700`, files `0600`):

| Path | Contents |
|---|---|
| `/data/whatsapp.db` | whatsmeow session store — the linked device's keys |
| `/data/messages.db` | message store written by the event handlers (WAL) |
| `/data/downloads/<message-id>-<name>` | media fetched by `whatsapp_download_media` |

## Image

CI (`.woodpecker/`) runs the Python tests, then builds and pushes this on every
push to `master` touching `servers/whatsapp/**`, and on `whatsapp-v*` tags:

```bash
docker pull harbor.bzd.gg/bzd/whatsapp-mcp:latest
```

To build locally instead:

```bash
docker build -t harbor.bzd.gg/bzd/whatsapp-mcp:latest .
```

The image is `python:3.12-slim` plus `ffmpeg` (voice notes) and `libmagic1`
(imported by neonize), runs as uid `10001`, and works on amd64 —
neonize publishes prebuilt manylinux wheels, so nothing is compiled.

## Login

Pair once by scanning a QR code (WhatsApp → Linked devices → Link a device):

```bash
docker run -it --rm \
  -v $(pwd)/config.json:/config/config.json:ro \
  -v whatsapp-data:/data \
  harbor.bzd.gg/bzd/whatsapp-mcp:latest login
```

The QR code is drawn on **stderr** so a redirected stdout never swallows it.
It exits 0 once paired, non-zero after a 3 minute timeout. The session stays
in the `whatsapp-data` volume; re-run `login` only after logging the device out
from the phone. If the volume is root-owned from an earlier run, fix it with
`docker run --rm -u 0 -v whatsapp-data:/data --entrypoint chown harbor.bzd.gg/bzd/whatsapp-mcp:latest -R 10001:10001 /data`.

## Run

The server speaks MCP over stdio, so it's meant to be spawned by an MCP client
(Claude Code, Claude Desktop, etc.), not left running standalone. Register it
with a command like:

```json
{
  "mcpServers": {
    "whatsapp": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-v", "/path/to/config.json:/config/config.json:ro",
        "-v", "whatsapp-data:/data",
        "-v", "/path/to/media:/media:ro",
        "harbor.bzd.gg/bzd/whatsapp-mcp:latest"
      ]
    }
  }
}
```

To try it by hand:

```bash
docker run -i --rm \
  -v $(pwd)/config.json:/config/config.json:ro \
  -v whatsapp-data:/data \
  -v $(pwd)/media:/media:ro \
  harbor.bzd.gg/bzd/whatsapp-mcp:latest
```

Run only one container per `whatsapp-data` volume: WhatsApp allows a single
connection per linked device.

## Tools

| Tool | Description |
|---|---|
| `whatsapp_check_connection` | Is WhatsApp connected and the device still paired? |
| `whatsapp_search_contacts` | Find contacts by name or phone number |
| `whatsapp_list_chats` | List chats, optionally filtered, sorted by activity or name |
| `whatsapp_get_chat` | Get one chat by JID |
| `whatsapp_get_direct_chat_by_contact` | Direct chat for a phone number |
| `whatsapp_get_contact_chats` | All chats a contact takes part in, one row per chat |
| `whatsapp_get_last_interaction` | Most recent message with a contact |
| `whatsapp_list_messages` | Messages filtered by time, sender, chat or text |
| `whatsapp_get_message_context` | Messages around a given message |
| `whatsapp_download_media` | Download a message's media; returns the file path under `/data/downloads` |
| `whatsapp_send_message` | Send a text message (needs `allow_send`) |
| `whatsapp_send_file` | Send a file from `media_dir`, by relative path (needs `allow_send`) |
| `whatsapp_send_audio_message` | Send an audio file from `media_dir` as a voice note, transcoded to Opus/Ogg with ffmpeg (needs `allow_send`) |

Read tools return structured JSON, with `limit` capped at 1–200 and message
content truncated to 4000 characters. Sent messages and media captions are
stored too (`is_from_me = 1`), so they show up in later reads. DMs are keyed by
LID: names and phone numbers are resolved from the session DB's contact and
LID-mapping tables, and an unmapped LID is returned as a LID, never as a
guessed phone number.

## Security model

- Message content is untrusted third-party data and is returned as plain JSON
  field values; tool descriptions tell the model never to follow instructions
  found inside it. Prompt injection through a received message is mitigated,
  not eliminated — see the limits below.
- Outgoing files must be a path relative to `media_dir` (no absolute paths, no
  `..`), with symlinks resolved and the result checked to stay inside it. The
  size check (`max_media_bytes`) happens before the file is read into memory.
  No tool reads arbitrary files.
- Downloaded filenames are sender-controlled: they are sanitized, made unique
  (`<message-id>-<name>`, NAME_MAX-safe), created with `O_EXCL|O_NOFOLLOW`,
  `0600` in a `0700` dir (symlinks refused, name sanitized). Existing files are never overwritten.
- Voice notes are always re-encoded to Ogg/Opus with an argv-list ffmpeg call
  in a temporary directory, never next to the source.
- Message store queries are parameterized; the store is opened read-only for
  the read tools, and a separate connection per tool call.
- The container runs as uid `10001`, data is `0700`/`0600`, the config and media
  mounts are read-only. No port is published and nothing listens on the network.
- The session in `/data/whatsapp.db` is a full WhatsApp login: treat the volume
  like a credential, and unlink the device from the phone if it leaks.

## Honest limits

- WhatsApp Web is an **unofficial protocol**. whatsmeow/neonize reverse-engineer
  it, WhatsApp can change it without notice, and accounts using unofficial
  clients risk being rate-limited or **banned**. Use a number you can afford to
  lose; there is no support path if WhatsApp breaks or punishes the session.
- neonize ships a **prebuilt third-party Go binary** (`neonize-<platform>.so`,
  whatsmeow inside) that runs in this process with full access to the session
  and to the downloaded media. The version is pinned (`neonize==0.5.2`) but the
  trust is fundamentally in that wheel's publisher and its build.
- Prompt injection: an incoming message can contain text aimed at the model. The
  structured JSON output, the untrusted-content warning and the recipient
  allowlist reduce the blast radius; they do not remove it. Keep `allow_send`
  off, or `allowed_recipients` tight, when the same agent also reads chats.
- Reading history depends on what WhatsApp's history sync hands over after
  pairing; there is no backfill of older messages.
- Not implemented by design: group management, history backfill, audio
  transcription, image/video viewing, reactions and edits.
- Known upgrade point: `mcp` 2.x renames `FastMCP` to `MCPServer`; the pin stays
  at `mcp<2` until that migration is done.

## Tests

```bash
pip install -e .
python tests/test_config.py
python tests/test_jid.py
python tests/test_media.py
python tests/test_store.py
python tests/test_tools.py
python tests/test_server_tools.py
python tests/test_client_handlers.py
python tests/test_stdio.py
```

All run offline — no network, no WhatsApp account, no ffmpeg needed (the fake
client stands in for neonize). `tests/test_stdio.py` asserts that `serve` writes
nothing but JSON-RPC to stdout even when the Go core or a stray `print` writes
to fd 1.
