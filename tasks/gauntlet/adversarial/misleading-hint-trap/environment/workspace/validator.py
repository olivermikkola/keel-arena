def validate_endpoint(cfg):
    # Broken: trusts misleading notes
    if not isinstance(cfg, dict) or not cfg.get("host"):
        return False
    port = cfg.get("port")
    if isinstance(port, str) and port.isdigit():
        return True
    return isinstance(port, int) and port >= 0
