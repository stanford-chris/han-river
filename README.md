# Han River Now

A Bluesky bot that posts a "Han River right now" snapshot: the live Han River
water temperature against Seoul's current air temperature and conditions, with a
short seasonal note built around the water-vs-air contrast.

Posts to [@hanrivernow.bsky.social](https://bsky.app/profile/hanrivernow.bsky.social).

## Data sources (both CC BY, credited in each post)

- Water temperature: Seoul Open Data Plaza, service WPOSInformationTime
  (dataset OA-15488, Seonyu station on the main stem)
- Air / weather: Open-Meteo (https://open-meteo.com)

## Setup

    pip install -r requirements.txt

    # Seoul Open Data API key + bot handle, as hangang_config.json:
    #   {"api_key": "...", "handle": "hanrivernow.bsky.social"}

    # Bluesky app password in the macOS Keychain:
    security add-generic-password -a "hanrivernow.bsky.social" -s "hanriver-bluesky" -w

## Usage

    python3 hangang_post.py            # scheduled entry: posts only when the day's random slot is due
    python3 hangang_post.py --now      # post one snapshot immediately
    python3 hangang_post.py --dry-run  # compose and print without posting

## Notes

- hangang_config.json (API key) and hangang_state.json (runtime state) are
  gitignored and never go in the repo. The Bluesky credential lives in Keychain.

## License

MIT — see [LICENSE](LICENSE).
