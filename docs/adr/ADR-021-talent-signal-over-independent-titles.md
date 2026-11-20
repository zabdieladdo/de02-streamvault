# ADR-021: A director or lead actor signals a title worth licensing only on three or more independent titles, two-thirds of them above the list median

- **Status:** Accepted
- **Date:** 2026-11-20
- **Decision owner:** Noell

## Context

Kwame asked which directors and lead actors reliably signal a title worth licensing. An actor in every film of one series looks consistent, but what is measured is the series.

## Decision

Each collection counts once per person (a "title"); a standalone film is a title on its own. A person is "consistently above on return" with at least 3 titles and at least two-thirds above the list-wide median multiple (S25), "consistently below on return" with at least 3 and at most one-third above. Two titles both above is "above on return, too little evidence". Directors and lead actors are reported separately; the share of titles above the median vote count is shown beside it. Labels name the measure because the vote measure often disagrees. The signal is an all-years measure.

## Alternatives considered

### Alternative A: Median multiple of all the person's films, at least 3 films

- **How it would work:** rank people by their films' median multiple.
- **Why it is attractive:** simple, more names qualify.
- **Why rejected:** franchise actors and directors are measured by their series, counted once per film.

## Consequences

- **What this buys:** measured: directors: Steven Spielberg consistently above on return (4 of 4 titles); Christopher Nolan consistently below (0 of 5, his three Dark Knight films counting as one title). Lead actors: Harrison Ford and Liam Neeson consistently above (2 of 3 each); Al Pacino, Christian Bale and Michael Caine consistently below. Above but too little evidence: Quentin Tarantino, Robert Zemeckis, James Cameron; Uma Thurman, Michael Biehn, Tom Hanks.
- **What this costs:** few names qualify; evidence is not independent across people (Bale is in 4 of Nolan's films and Caine in 3, which is all of Caine's films on the list); return and audience interest disagree (Spielberg's vote hit rate is 0.25; Nolan directed the two most-voted films on the list, Interstellar and Inception).
- **What it costs the client if I am wrong:** a negotiator could undervalue a director audiences seek out because his films are expensive.
- **What would make me revisit this:** viewing data by director or actor.

## What this survives

At 500 titles more people reach three titles; the threshold is a setting in `config.py`.
