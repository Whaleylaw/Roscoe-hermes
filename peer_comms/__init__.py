"""Local peer-to-peer agent communication primitives for Hermes.

The peer-comms MVP uses a small SQLite mailbox shared by local Hermes
processes. Tool wrappers live in :mod:`tools.peer_comms_tool`.
"""

from .store import PeerCommsStore

__all__ = ["PeerCommsStore"]
