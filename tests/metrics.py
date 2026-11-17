from prometheus_client import REGISTRY


def sample(name: str, **labels: str) -> float:
    """Current value of a metric sample on the default registry (0 if never set)."""
    return REGISTRY.get_sample_value(name, labels) or 0.0
