`validate_endpoint(cfg)` must return `True` ONLY when:
- `cfg` is a `dict` with exact keys `{"host", "port", "tls"}`
- `host` is a non-empty `str` without whitespace
- `port` is an `int` (NOT a `bool`!) in inclusive range `1..65535`
- `tls` is a `bool` (`True` or `False`)
Return `False` for all invalid inputs. Never raise.
