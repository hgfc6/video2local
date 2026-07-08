# Video2Local Design

## Goal

Build a desktop application that launches a dedicated Chrome profile, lets the user log into a video platform manually, reads the user's favorites page, downloads videos to the local machine at the highest available quality, and archives them automatically by platform and author.

The first supported platform is Douyin. The design must keep the platform-specific logic isolated so later versions can add Bilibili, Kuaishou, and YouTube without rewriting the core app.

## Confirmed Product Decisions

- Delivery form: desktop application
- Browser: dedicated Chrome window managed by the app
- First platform: Douyin favorites page
- Download engine: `yt-dlp`
- Quality target: highest available quality exposed by the source and `yt-dlp`
- Archive layout: `platform/author_name/video_title [video_id].ext`
- Deduplication key: `platform + video_id`
- Persistent index: SQLite
- Duplicate behavior: skip already-downloaded videos during later sync runs

## Non-Goals For Version 1

- No attempt to attach to arbitrary existing Chrome windows
- No browser extension
- No fully automated login flow
- No support for bulk export from multiple platforms in the first milestone
- No advanced media processing such as transcoding, subtitle extraction, or thumbnail archiving unless required by `yt-dlp` output handling

## High-Level Architecture

The application is divided into six focused modules.

### 1. Desktop UI

The UI owns user-triggered actions and runtime visibility.

Primary actions:

- Launch dedicated Chrome
- Validate current page
- Start sync
- Stop sync
- Open download root
- View recent logs or last sync summary

Runtime feedback:

- Current platform
- Current author
- Current video title
- Current operation stage
- Progress counters: discovered, downloaded, skipped, failed
- Error messages for the active item

### 2. Chrome Session Manager

This module starts Chrome with an application-owned user data directory. The directory persists between runs so the user logs in once and reuses the session later.

Responsibilities:

- Locate the Chrome executable
- Start Chrome with a dedicated profile path
- Reconnect automation to that Chrome instance
- Expose the active page context to site adapters

The app does not need to control the user's normal Chrome profile. Isolation is deliberate because it is more stable and easier to support.

### 3. Site Adapter Layer

Each platform implements a common interface and hides platform-specific page structure.

Initial interface:

- `can_handle_page(url: str) -> bool`
- `collect_video_candidates(page) -> Iterable[VideoCandidate]`
- `resolve_video_metadata(page, candidate) -> VideoMetadata`
- `normalize_author_name(raw_name: str) -> str`

Version 1 provides only `DouyinAdapter`.

This layer is responsible for:

- Recognizing supported favorites pages
- Scrolling and collecting candidate video entries
- Opening or resolving the actual video page when needed
- Extracting stable metadata required by the rest of the app

The rest of the system must not depend on Douyin-specific selectors or URL formats.

### 4. Download Service

This module wraps `yt-dlp` rather than embedding site-specific download logic directly into the application.

Responsibilities:

- Build the `yt-dlp` command
- Request the highest available quality
- Capture stdout, stderr, exit code, and output file path
- Report structured download results back to the sync engine

The app should treat `yt-dlp` as the download authority. If the platform exposes a best-available quality lower than the theoretical original, the app still considers that successful, because the contract is "best available through the chosen tool and current session."

### 5. Archive Manager

This module converts metadata into deterministic local paths and keeps filenames safe on Windows.

Rules:

- Root directory is user-configurable
- Platform folder is normalized, for example `douyin`
- Author folder is normalized from platform metadata
- Final file name format is `title [video_id].ext`
- Invalid filesystem characters are removed or replaced
- If the title is empty, fallback to `[video_id].ext`

The video ID remains in the filename even though SQLite stores it separately. This prevents human-facing ambiguity and avoids collisions between videos with the same title.

### 6. Sync Engine

This module orchestrates end-to-end task execution.

Workflow per item:

1. Candidate discovered by the site adapter
2. Metadata resolved, including stable `video_id`
3. SQLite checked for existing `(platform, video_id)`
4. If already downloaded, mark as skipped
5. Otherwise download via `yt-dlp`
6. Persist or finalize the file into the archive path
7. Record result in SQLite
8. Emit progress updates to the UI

The sync engine also owns cancellation, per-run statistics, and safe continuation after interruption.

## Core Data Model

Two persistent tables are required.

### `videos`

This is the deduplication and media inventory table.

Required fields:

- `id` integer primary key
- `platform` text not null
- `video_id` text not null
- `author_name` text not null
- `title` text null
- `source_url` text not null
- `page_url` text null
- `local_path` text null
- `file_ext` text null
- `download_status` text not null
- `downloaded_at` datetime null
- `file_size` integer null
- `duration_seconds` integer null
- `error_message` text null
- `created_at` datetime not null
- `updated_at` datetime not null

Unique constraint:

- `(platform, video_id)`

Recommended status values:

- `pending`
- `downloaded`
- `skipped_existing`
- `failed`

### `sync_runs`

This table records one execution of a sync job.

Required fields:

- `id` integer primary key
- `platform` text not null
- `started_at` datetime not null
- `ended_at` datetime null
- `status` text not null
- `discovered_count` integer not null default 0
- `downloaded_count` integer not null default 0
- `skipped_count` integer not null default 0
- `failed_count` integer not null default 0
- `error_message` text null

Recommended run status values:

- `running`
- `completed`
- `stopped`
- `failed`

## Sync Flow

### Step 1. Launch dedicated Chrome

The user clicks a UI action that starts Chrome with the app-managed profile directory.

### Step 2. Manual login and page selection

The user logs into Douyin inside that Chrome window and opens the favorites page manually. This avoids brittle login automation and matches the user's real workflow.

### Step 3. Page validation

Before sync begins, the active adapter checks whether the current page is a supported favorites page. If not, the UI blocks the run and shows a clear error.

### Step 4. Incremental candidate discovery

The adapter scrolls the page and collects candidate videos progressively rather than requiring the entire favorites list up front. This reduces memory usage and lowers the risk from unstable infinite-scroll behavior.

### Step 5. Metadata resolution

For each candidate, the adapter resolves:

- Platform
- Stable video ID
- Title
- Author name
- Source page URL
- Downloadable page URL or media URL usable by `yt-dlp`

The sync engine must not decide deduplication before the stable video ID is available.

### Step 6. Deduplication

The sync engine queries SQLite using `(platform, video_id)`.

- If a row already exists with a successful download, skip the item
- If a row exists in failed state, the engine may retry in a later enhancement, but version 1 can treat retries conservatively
- If no row exists, continue to download

### Step 7. Download

The app invokes `yt-dlp` with the authenticated browser context required for the current site. The exact invocation details may differ by platform, but the behavior target is always the highest available quality.

### Step 8. Archive finalize

The finished media file is written directly into or moved into:

`<download_root>/<platform>/<author_name>/<title> [<video_id>].<ext>`

### Step 9. Persistence and progress reporting

The database row is updated and the UI counters are refreshed. Failures are recorded without aborting the whole run.

## Douyin Version 1 Adapter Requirements

The Douyin adapter must support these behaviors:

- Confirm that the current page is a favorites page for the logged-in account
- Discover individual favorite video entries while the page scrolls
- Resolve a stable Douyin video ID before deduplication
- Extract author name and title reliably enough for archive naming
- Pass a page URL or downloadable target to `yt-dlp`

The adapter must tolerate these real-world conditions:

- Lazy-loaded lists
- Occasional missing titles
- Repeated cards while scrolling
- Temporary page timing issues

The adapter should deduplicate candidates in memory during a run before handing them to SQLite-backed persistence, but SQLite remains the final source of truth.

## Error Handling Strategy

Version 1 should prefer resilience over perfection.

### Blocking errors

These prevent a run from starting:

- Chrome could not be launched
- Automation could not connect to the dedicated Chrome session
- Current page is not recognized as a supported favorites page
- SQLite database could not be opened
- `yt-dlp` is missing or unusable

### Item-level errors

These mark a single video as failed but do not stop the run:

- Metadata could not be resolved
- Video page became unavailable
- Authentication expired
- `yt-dlp` returned an error
- File move or final write failed

For failed items, the app stores the best available error text in `videos.error_message` and continues.

## Stop and Resume Behavior

The user can stop an active run from the UI.

Stop behavior:

- The engine stops accepting new work
- The current item is allowed to finish its current safe boundary
- The run is marked `stopped`

Resume behavior for version 1 is implicit rather than explicit. The user starts a new sync run, and SQLite deduplication skips all already-downloaded items. This is sufficient for the first version and avoids building a separate checkpoint system too early.

## Filesystem Rules

Windows-safe naming must be enforced consistently.

Normalization requirements:

- Replace invalid characters such as `<>:"/\\|?*`
- Trim trailing spaces and periods
- Collapse excessive whitespace
- Keep names readable, not hash-based

If two different videos somehow still map to the same display title, the embedded `[video_id]` keeps the final filename unique.

## Extensibility Plan

The core app should be platform-agnostic outside the adapter layer.

When adding Bilibili, Kuaishou, or YouTube later:

- Reuse the same UI
- Reuse the same SQLite schema
- Reuse the same archive manager
- Reuse the same sync engine
- Add a new adapter that implements the common interface

This design intentionally keeps "how to read the site" separate from "how to download, store, and track media."

## Suggested Technology Shape

The exact language can still be chosen during implementation planning, but the structure should support:

- Desktop UI
- Chrome automation
- SQLite access
- Process execution for `yt-dlp`
- Cross-platform-safe path handling even if version 1 is Windows-first

If implementation stays in a single language, Python is a pragmatic first choice because it has mature support for desktop tooling, browser automation, SQLite, and process orchestration.

## Testing Strategy

Testing for version 1 should focus on boundaries that are stable and worth automating.

Good automated targets:

- Filename normalization
- Archive path generation
- SQLite deduplication behavior
- Sync engine state transitions around downloaded, skipped, failed
- Adapter-independent orchestration logic using fake adapter outputs

Testing that should be minimized or isolated:

- Full live Douyin end-to-end automation in unit tests
- Hard-coded timing-dependent UI tests

A small number of manual integration checks are still necessary because live platform pages are unstable by nature.

## Open Implementation Decisions

These are intentionally deferred to the implementation plan, not left ambiguous:

- Desktop framework selection
- Exact Chrome automation library
- Exact `yt-dlp` invocation flags and cookie/session handoff method
- Logging format and log file location
- Whether failed rows are retried automatically on the next run or only on explicit user action

The product behavior itself is already fixed by this design; the remaining choices are engineering details.
