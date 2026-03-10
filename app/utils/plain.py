from typing import Any


def to_plain(value: Any) -> Any:
    """
    Recursively convert a value (potentially containing ruamel.yaml CommentedMap/CommentedSeq)
    into a plain Python dict/list structure.
    """
    if isinstance(value, dict):
        return {str(k): to_plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_plain(v) for v in value]
    return value
