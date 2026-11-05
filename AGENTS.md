# Working on Leika

Leika is a standalone visualization library. The global working agreement
applies. `docs/` documents current behavior, and
[docs/development.md](docs/development.md) covers setup, builds and checks.
[docs/WORK_BRIEF.md](docs/WORK_BRIEF.md) is the work brief and lists the
projects that install Leika.

Every change to the installed package (`src/leika/`, the browser client
included) reaches every project being worked on as part of the same work. Pin
the commit in each project and install it from that commit (`pip install
--no-deps --force-reinstall`, since the version number does not change); the
install builds the browser client, so it needs Node.js 24's `npm` on `PATH`. A
running viewer keeps the Python it imported but serves the installed page from
disk, so when Python changes, the viewers in each updated environment need a
restart. Before changing a project's pin, ask the session working in that
project, when one is reachable; tell it once done.
