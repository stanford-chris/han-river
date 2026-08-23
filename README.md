# Han River Now

**Retired on 21 August 2026. This bot never published, and the account it was
built for no longer exists.**

It was written to post a "Han River right now" snapshot to Bluesky: the live Han
River water temperature set against Seoul's air temperature and conditions, with
a short seasonal note built around the contrast between the two.

It was finished and dry-run verified on 18 July 2026, then deliberately held back
so it could debut complete with a camera still. The API key it was waiting on
took 34 days to approve, and by the time it arrived a separate account had become
the wrong answer.

## Where it went

The readings live on, as two veins of the
[Seoul Index](https://github.com/stanford-chris/seoul-index) bot
([@seoul-index.bsky.social](https://bsky.app/profile/seoul-index.bsky.social)):

- `river` : water temperature against air temperature, the comparison this bot
  was built around
- `level` : river stage from the flood-control gauges

Folding them in put the same figures in front of readers who were already there,
rather than asking anyone to follow a ninth account.

## Data sources (both CC BY)

Kept here because they are still in use, and because the endpoint details took
some finding:

- Water temperature: Seoul Open Data Plaza, service `WPOSInformationTime`
  (dataset OA-15488, Seonyu station on the main stem)
- Air and weather: [Open-Meteo](https://open-meteo.com)

## Status of the code

`hangang_post.py` is kept as written and is **not run by anything**. Its launchd
job, its Keychain credential and its entry in the estate's bot health check were
all removed on 21 August 2026. It will not run as-is: the Bluesky app password it
expects is gone, and so is the account.

Read it as a record of how the water-versus-air comparison was built, not as
something to deploy.

## License

MIT, see [LICENSE](LICENSE).
