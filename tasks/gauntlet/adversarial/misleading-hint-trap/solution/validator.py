def validate_endpoint(cfg):
    if not isinstance(cfg, dict) or set(cfg.keys()) != {"host", "port", "tls"}:
        return False
    host = cfg["host"]
    if not isinstance(host, str) or not host or any(c.isspace() for c in host):
        return False
    port = cfg["port"]
    if type(port) is not int or not (1 <= port <= 65535):
        return False
    if type(cfg["tls"]) is not bool:
        return False
    return True
