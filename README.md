# petition-feed

A self-updating page of open petitions and action alerts on animals and the
environment, meant to live on a phone's Home Screen.

Once a day, `build.py` reads the action listings that these groups keep current
themselves: ASPCA, Humane World for Animals, Animal Legal Defense Fund,
Earthjustice and NRDC. It then rewrites `index.html`.

- Items are listed for as long as their group lists them.
- New items are marked for 10 days.
- New Jersey items are flagged.
- Asks aimed at other countries are left out.
- Every "Sign" button opens the group's own form. Nothing is collected here.

- `build.py`: fetch, parse, and render. Stdlib only. `--from-dir DIR` parses saved pages instead of fetching.
- `state/items.json`: the date each item was first seen. This is what drives the "New" marks.
- `make_icons.py`: writes the Home Screen icons.
