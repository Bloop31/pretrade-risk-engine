# Editing risk limits

This guide is for the people who own the risk limits. You do not need to be a
developer. All limits live in one file, `config/rules.yaml`. You edit it, save
it, and the service picks up the change by itself within about two seconds. No
restart is needed.

**You cannot break trading by making a typo.** If the file has a mistake, the
service ignores the new file, keeps using the last good one, and tells you
exactly what is wrong (see [If something is wrong](#if-something-is-wrong)).

## What the file looks like

```yaml
schema_version: 1          # leave this as 1

trading_enabled: true      # set to false to stop ALL trading

defaults:                  # apply to everyone unless overridden below
  max_order_quantity: 10000
  max_order_notional: 1000000
  price_collar_pct: 5
  max_position: 50000
  max_gross_exposure: 10000000
  max_orders_per_second: 50
  max_price_age_seconds: 30

restricted_symbols:        # nobody may trade these
  - XYZ

symbols:                   # tighter or looser limits for particular symbols
  TSLA:
    max_order_quantity: 2000

accounts:                  # limits for particular accounts
  HEDGE-01:
    max_gross_exposure: 50000000
    symbols:               # ...and for particular symbols in that account
      AAPL:
        max_position: 200000
  SUSPENDED-01:
    trading_enabled: false # stop one account
```

## The limits

All limits are **inclusive**: an order exactly at the limit is accepted.

| Limit | What it means | Example |
|---|---|---|
| `max_order_quantity` | The most shares/contracts in a single order. | `10000`: an order for 10,001 is rejected. |
| `max_order_notional` | The most a single order may be worth: quantity × price. | `1000000`: 5,000 shares at 250 (= 1,250,000) is rejected. |
| `price_collar_pct` | How far, in percent, a limit price may be from the last market price. Catches mistyped prices. | `5`: with the market at 100, a buy at 106 is rejected. |
| `max_position` | The largest position an account may hold in one symbol, long or short, counting orders not yet filled. | `50000`: holding 49,000 and buying 2,000 is rejected. |
| `max_gross_exposure` | The most an account may have at risk across all symbols: the total value of all its positions, long and short added together. | `10000000` |
| `max_orders_per_second` | How many orders one account may send per second. | `50` |
| `max_price_age_seconds` | How old the last market price may be. If prices stop arriving (a feed outage), orders in that symbol are rejected rather than checked against an out-of-date price. | `30`: with no price update for 31 seconds, orders are rejected. |

Two more settings:

| Setting | Where | What it means |
|---|---|---|
| `trading_enabled: false` | top of the file | Stops **all** trading. |
| `trading_enabled: false` | under an account | Stops that account only. |
| `restricted_symbols` | top of the file, or under an account | Symbols that may not be traded, by anyone or by that account. |

`max_price_age_seconds` can be set per symbol too: an illiquid symbol that
updates rarely may need a longer limit than a busy one.

Orders that **reduce** risk are always allowed through the position and
exposure limits, even if the account is already over them. If you lower a
limit below where an account already is, it can still trade back down.

## Which limit applies

A limit can be set in up to four places. For each order, the **most specific**
one wins:

```
1. defaults                          (everyone, everything)
2. symbols.TSLA                      (everyone trading TSLA)
3. accounts.HEDGE-01                 (everything HEDGE-01 trades)
4. accounts.HEDGE-01.symbols.TSLA    (HEDGE-01 trading TSLA)   ← most specific
```

Anything not set at a level falls through to the level above. Every limit must
be set under `defaults`, so there is always a value.

`max_gross_exposure` and `max_orders_per_second` are per account, so they can
only be set under `defaults` or an account, not under a symbol.

To see the exact limits an order would get, ask the service (an operator can
run this for you):

```
GET /admin/rules/limits?account=HEDGE-01&symbol=TSLA
```

## Writing numbers

- Write plain numbers: `1000000`, `2.5`, `0.25`. They are read exactly as written.
- You may use underscores to make big numbers readable: `10_000_000`.
- Don't use commas (`1,000,000`), currency symbols (`$`) or percent signs (`5%`).
  `price_collar_pct: 5` already means five percent.
- Limits must be positive. `max_position` and `max_gross_exposure` may be `0`,
  which means "reduce only": the account may only trade towards flat.

## Names

- Symbols are written in capitals: `AAPL`, `BRK.A`. Lower case is accepted and
  converted. Writing the same symbol twice (`aapl` and `AAPL`) is an error.
- Account IDs are written exactly as they appear on orders, and are
  case-sensitive.
- Indentation matters: use spaces, not tabs, and keep items under the same
  heading lined up.

## If something is wrong

If the file you saved can't be used, the service **keeps the previous rules**
and records the problems. Ask an operator to check `GET /admin/rules`; the
`rejected_file` section lists every problem, with its location in the file:

```json
"rejected_file": {
  "problems": [
    "defaults.max_postion: Extra inputs are not permitted",
    "defaults.max_position: Field required"
  ]
}
```

That reads as: under `defaults`, `max_postion` is not a known setting (it's a
misspelling), and the real `max_position` is missing. Fix the file and save
again; the problems disappear once a good file is loaded.

Common messages:

| Message | Meaning |
|---|---|
| `Extra inputs are not permitted` | A setting name is misspelt, or is in a place it isn't allowed (e.g. `max_gross_exposure` under a symbol). |
| `Field required` | A limit is missing from `defaults`. |
| `Input should be greater than 0` | A limit is zero or negative. |
| `Input should be less than or equal to 100` | `price_collar_pct` is over 100. |
| `found duplicate key` | The same name appears twice under one heading. |
| `are the same symbol` | The same symbol is written twice in different cases. |
| `YAML syntax error` | Usually indentation, or a missing `:` after a name. |

## Checklist before saving

1. Is every number plain, with no commas, `$` or `%`?
2. Are new entries indented to line up with their neighbours?
3. After saving, check `GET /admin/rules`: the `version` should change, and
   there should be no `rejected_file`.
