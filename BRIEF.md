# Preached — project brief

Entry for the **AI for Church Hackathon 2026** (https://aiforchurch.com/hackathon).
Owner: Patrick Shouse (GitHub `pshouse`). Deacon over tech & media at Gaston
Community Church, Gastonia NC. Day job: leads Technology Solutions for the
single-family rental business at Bridge Investment Group.

## What we're building

**Preached**: search a church's whole sermon archive and hear the answer in the
preacher's own words.

- A user asks a question ("What has our pastor taught about anxiety?").
- The app returns the exact moments across all sermons where it was addressed,
  with the video/audio queued to that second.
- Answers are always the preacher's own words (clips + transcript excerpts).
  **The AI finds; it never paraphrases or speaks for the pastor.** This is a
  deliberate design rule, not a limitation.
- Any church can use it: paste a YouTube channel and it builds the library.
- A built-in public-domain library of classic preachers (John Wesley first)
  lets members hear how the same question was answered through church history,
  side by side with their own pastor.

Track: **Discipleship & Spiritual Growth**.

## Hard constraints (hackathon rules)

- **Build window: Oct 30 – Nov 27, 2026, 11:59 PM ET.** Only work done in this
  window is judged. All commits to this repo must land inside it. Don't import
  pre-existing code wholesale; the existing sermon-shorts pipeline may be
  *called* but what's judged is what's new here.
- Must be built with AI and/or use AI in what it does.
- **Privacy:** no real personal information of church members in the demo.
  Sermons themselves are fine (public teaching), but flag and strip congregant
  names from transcripts (e.g. "my friend Dave in the choir"); stripping is
  assisted, not guaranteed, and a human reviews before publishing. Avoid
  crowd shots. Use sample data for anything member-related.
- Content must be theologically sound, honest about AI, keep humans in the loop.
- Submission: name, ≤250-word description, track, **demo video ≤5 min**
  (YouTube/Vimeo/Loom); live demo link and repo optional but we'll provide both.

## Judging weights

| 30% | Ministry Impact |
| 25% | Execution & Quality (does it work, reliable, usable) |
| 20% | Innovation |
| 15% | Faithfulness & Responsible AI (sound, honest, private, human in loop) |
| 10% | Presentation (demo video + write-up) |

Judges: Justin Dean (AI for Church), Christopher Nelson (10x10 Group),
Corey Alderin (CEO, Sermon Shots), Joy Drake (AgentJoy). Two are church
marketing people; one runs a sermon-clipping product (Sermon Shots), so
**do not drift into a clipping tool**, that's their product.

## Positioning vs. existing tools

- **spurgeon.ai**: semantic search over 3,192 Spurgeon sermons. Text only,
  one dead preacher, AI summary. We differ: any church's own archive,
  timestamped audio/video, no AI paraphrase.
- **SermonAudio "Ask!"**: Q&A over sermons from churches on their platform.
- **Sermon Shots**: clips, captions, devotionals, blog posts from a sermon.
  Searches within one sermon; we search across the whole archive.

## Infrastructure

- **Repo:** https://github.com/pshouse/preached (private, this repo).
- **Runtime:** Fly.io Sprite `preached` → https://preached-blncn.sprites.app
  (private; auth = sprite, admins only). Sprites API at https://api.sprites.dev
  (OpenAPI at /openapi.json; exec, fs, services endpoints available).
- **Existing pipeline (do not copy, call it):** Sprite `sermon-shorts`
  (https://sermon-shorts-blncn.sprites.app). Holds full service recordings
  (`Live_YYYY-MM-DD_7am.mp4`), detected sermon segments (`*_sermon.mp4`),
  `*.sermon-windows.json` and Whisper transcripts
  (`*.transcript-medium.json`, one `transcript-large-v3`). It detects the
  sermon inside a livestream and transcribes it.
- **Church sermons on YouTube:** Gaston Community Church channel (pastor's
  permission still being requested; don't publish anything with it until
  confirmed).

## Demo data (public domain, verified available)

All on archive.org / LibriVox, public-domain audio (volunteer readers):

- **John Wesley, *Sermons on Several Occasions*** — primary demo library, ~71 h:
  `sermonsfirstseries_1307_librivox`, `sermonssecondseries_1503_librivox`,
  `sermons3to5series_1511_librivox`
- Jonathan Edwards, *Select Sermons* (~20 h): `select_sermons_edwards_0911_librivox`
- Spurgeon, *Sermons May 1858* (~4 h): `spurgeons_sermons_librivox`
- Calvin, *Most Celebrated Sermons*: `mostcelebratedsermonsjohncalvin_2104_librivox`
- Also available: Chrysostom homilies (~200 h), Newman, Luther,
  Moody, Catherine Booth, Thomas Watson, Thomas Manton.
- ~~Talmage~~ **Dropped** (Patrick's decision, Oct 30): no Talmage library,
  including the historical recording *Sermon on the Mount* (1898),
  `SermonOnTheMountByT.DeWittTalmage1898`.
- Audio files are served from `*.us.archive.org`. Metadata via
  `https://archive.org/metadata/<identifier>`.
- Sermon *text* for cross-checking transcripts: ccel.org (public domain).
- **Caution:** do not bulk-import by tag. The "sermons" tag on archive.org
  includes Christian Identity (white-supremacist) preachers. Curate by hand.

## Plan

- **Week 1 (Oct 30–Nov 5):** download + transcribe Wesley, build the index,
  prove question → exact timestamp at the command line.
- **Week 2:** web app with a player that jumps to the moment; YouTube channel
  import.
- **Week 3:** add church sermons (with permission), side-by-side classic
  preacher view, name-stripping for privacy, polish.
- **Week 4:** record the 5-min demo, write the 250-word description, submit
  a few days early. Deadline Nov 27, 11:59 PM ET. Winners Dec 1, 12 PM ET.

## Design rules for any agent working here

1. Never generate an answer in the preacher's voice. Return excerpts + timestamps.
2. Every result must cite sermon + timestamp and be playable from there.
3. Humans approve anything that gets published or sent.
4. Keep the stack simple enough to run on one Sprite.
5. Commit often; history is part of the evidence that work happened in-window.
