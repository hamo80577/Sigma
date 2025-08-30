# profiles_store.py
import os
import json
from typing import Dict, Optional
from cryptography.fernet import Fernet

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

PROFILES_PATH = os.path.join(DATA_DIR, "profiles.json")
KEY_PATH = os.path.join(DATA_DIR, "profiles.key")


class ProfilesStore:
    def __init__(self):
        self._fernet = self._load_or_create_key()

    def _load_or_create_key(self) -> Fernet:
        if not os.path.exists(KEY_PATH):
            key = Fernet.generate_key()
            with open(KEY_PATH, "wb") as f:
                f.write(key)
        else:
            with open(KEY_PATH, "rb") as f:
                key = f.read()
        return Fernet(key)

    def list_names(self):
        data = self._read_all()
        return sorted(list(data.keys()))

    def load(self, name: str) -> Optional[Dict]:
        data = self._read_all()
        return data.get(name)

    def save(self, name: str, profile: Dict):
        data = self._read_all()
        data[name] = profile
        with open(PROFILES_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def delete(self, name: str):
        data = self._read_all()
        if name in data:
            del data[name]
            with open(PROFILES_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def _read_all(self) -> Dict[str, Dict]:
        if not os.path.exists(PROFILES_PATH):
            return {}
        try:
            with open(PROFILES_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    # ---- encryption helpers ----
    def encrypt(self, plain: str) -> Optional[str]:
        if not plain:
            return None
        token = self._fernet.encrypt(plain.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, token: Optional[str]) -> Optional[str]:
        if not token:
            return ""
        try:
            plain = self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
            return plain
        except Exception:
            return ""
