"""Application-owned SQLite records; reads the existing database without a conversion."""
import json
from pathlib import Path
import sqlite3
import threading
from .errors import CyToolError

class RuntimeLock:
    def __init__(self,path):
        self.db=sqlite3.connect(str(path),timeout=.1,check_same_thread=False)
        try:self.db.execute('BEGIN EXCLUSIVE')
        except sqlite3.OperationalError:
            self.db.close();raise CyToolError('Busy','This data directory belongs to a running instance; use --connect.')
    def close(self):self.db.close()

class Store:
    def __init__(self,path):
        self.lock=threading.RLock();self.db=sqlite3.connect(str(path),check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS records(kind TEXT,id TEXT,value TEXT,PRIMARY KEY(kind,id))');self.db.commit()
    def put(self,kind,identifier,value):
        with self.lock:
            self.db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?)',(kind,identifier,json.dumps(value,ensure_ascii=False,allow_nan=False)));self.db.commit()
    def all(self,kind):
        with self.lock:return {identifier:json.loads(value) for identifier,value in self.db.execute('SELECT id,value FROM records WHERE kind=?',(kind,))}
    def close(self):self.db.close()
