from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple


class StateStore:
    """
    Thread-safe in-memory state store for the Vera Bot.
    Manages contexts across scopes, conversation state across multi-turn interactions,
    and suppression / deduplication keys.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self.start_time = time.time()
        
        # contexts: (scope, context_id) -> {"version": int, "payload": dict, "delivered_at": str}
        self.contexts: Dict[Tuple[str, str], Dict[str, Any]] = {}
        
        # suppression tracking
        self.suppressed_keys: Set[str] = set()
        self.suppressed_merchants: Set[str] = set()
        
        # conversations: conversation_id -> conversation metadata & turn history
        self.conversations: Dict[str, Dict[str, Any]] = {}

    def get_uptime_seconds(self) -> int:
        return int(time.time() - self.start_time)

    def store_context(
        self, scope: str, context_id: str, version: int, payload: Dict[str, Any], delivered_at: str
    ) -> Tuple[bool, Optional[str], Optional[int]]:
        """
        Stores context idempotently with version tracking.
        Returns: (accepted: bool, ack_id_or_reason: str, current_version: Optional[int])
        """
        with self._lock:
            key = (scope, context_id)
            current = self.contexts.get(key)
            
            if current is not None:
                cur_ver = current.get("version", 0)
                if version < cur_ver:
                    return False, "stale_version", cur_ver
                if version == cur_ver:
                    ack_id = f"ack_{context_id}_v{version}"
                    return True, ack_id, None

            # Store or update
            self.contexts[key] = {
                "version": version,
                "payload": payload,
                "delivered_at": delivered_at,
                "stored_at": datetime.now(timezone.utc).isoformat(),
            }
            ack_id = f"ack_{context_id}_v{version}"
            return True, ack_id, None

    def get_context(self, scope: str, context_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Retrieve payload for a given (scope, context_id)."""
        if not context_id:
            return None
        with self._lock:
            entry = self.contexts.get((scope, context_id))
            if entry:
                return entry.get("payload")
            return None

    def get_context_counts(self) -> Dict[str, int]:
        """Return count of loaded contexts per scope."""
        with self._lock:
            counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
            for (scope, _), _ in self.contexts.items():
                if scope in counts:
                    counts[scope] += 1
                else:
                    counts[scope] = counts.get(scope, 0) + 1
            return counts

    def is_suppressed(self, suppression_key: Optional[str], merchant_id: Optional[str] = None) -> bool:
        """Check if a suppression key or merchant is currently suppressed."""
        with self._lock:
            if merchant_id and merchant_id in self.suppressed_merchants:
                return True
            if suppression_key and suppression_key in self.suppressed_keys:
                return True
            return False

    def mark_suppressed(self, suppression_key: Optional[str], merchant_id: Optional[str] = None) -> None:
        """Mark a suppression key or merchant as suppressed."""
        with self._lock:
            if suppression_key:
                self.suppressed_keys.add(suppression_key)
            if merchant_id:
                self.suppressed_merchants.add(merchant_id)

    def record_action(self, action: Dict[str, Any]) -> None:
        """Record a bot proactive message / action in conversation state."""
        with self._lock:
            conv_id = action.get("conversation_id")
            if not conv_id:
                return
            
            supp_key = action.get("suppression_key")
            if supp_key:
                self.suppressed_keys.add(supp_key)

            conv = self.conversations.setdefault(
                conv_id,
                {
                    "conversation_id": conv_id,
                    "merchant_id": action.get("merchant_id"),
                    "customer_id": action.get("customer_id"),
                    "trigger_id": action.get("trigger_id"),
                    "turns": [],
                    "last_bot_body": action.get("body"),
                    "auto_reply_count": 0,
                    "is_ended": False,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            conv["turns"].append({
                "from": "vera" if action.get("send_as") == "vera" else "merchant_on_behalf",
                "role": "bot",
                "body": action.get("body"),
                "cta": action.get("cta"),
                "rationale": action.get("rationale"),
                "ts": datetime.now(timezone.utc).isoformat(),
            })
            conv["last_bot_body"] = action.get("body")

    def record_inbound_reply(
        self, conv_id: str, merchant_id: Optional[str], customer_id: Optional[str], from_role: str, message: str, turn_number: int
    ) -> Dict[str, Any]:
        """Record an inbound merchant or customer reply and return current conversation state."""
        with self._lock:
            conv = self.conversations.setdefault(
                conv_id,
                {
                    "conversation_id": conv_id,
                    "merchant_id": merchant_id,
                    "customer_id": customer_id,
                    "trigger_id": None,
                    "turns": [],
                    "last_bot_body": None,
                    "auto_reply_count": 0,
                    "is_ended": False,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            if merchant_id and not conv.get("merchant_id"):
                conv["merchant_id"] = merchant_id
            if customer_id and not conv.get("customer_id"):
                conv["customer_id"] = customer_id

            # Check if this message is identical to previous user messages (auto-reply detection helper)
            prev_user_messages = [t["message"] for t in conv["turns"] if t.get("role") == "inbound"]
            if prev_user_messages and prev_user_messages[-1] == message:
                conv["auto_reply_count"] += 1

            conv["turns"].append({
                "from": from_role,
                "role": "inbound",
                "message": message,
                "turn_number": turn_number,
                "ts": datetime.now(timezone.utc).isoformat(),
            })
            return conv

    def record_outbound_reply(self, conv_id: str, action: str, body: Optional[str], rationale: Optional[str], cta: Optional[str] = None) -> None:
        """Record the bot's response to an inbound reply."""
        with self._lock:
            conv = self.conversations.get(conv_id)
            if conv:
                if action == "end":
                    conv["is_ended"] = True
                if body:
                    conv["last_bot_body"] = body
                conv["turns"].append({
                    "from": "vera",
                    "role": "bot",
                    "action": action,
                    "body": body,
                    "cta": cta,
                    "rationale": rationale,
                    "ts": datetime.now(timezone.utc).isoformat(),
                })

    def get_conversation(self, conv_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self.conversations.get(conv_id)

    def end_conversation(self, conv_id: str, suppress_merchant: bool = False) -> None:
        with self._lock:
            conv = self.conversations.get(conv_id)
            if conv:
                conv["is_ended"] = True
                mid = conv.get("merchant_id")
                if suppress_merchant and mid:
                    self.suppressed_merchants.add(mid)

    def wipe_state(self) -> None:
        """Wipe state for teardown or clean test run."""
        with self._lock:
            self.contexts.clear()
            self.suppressed_keys.clear()
            self.suppressed_merchants.clear()
            self.conversations.clear()
            self.start_time = time.time()


# Global singleton instance
store = StateStore()
