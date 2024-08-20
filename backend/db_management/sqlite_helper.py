import sqlite3
from pydantic import BaseModel
from typing import Annotated, Sequence, TypedDict, Dict, Optional,List, Any,TypedDict

class SQLiteHelper(BaseModel):
    db_path:str
    conn:Any = None
    cursor:Any = None

    def open(self):
        self.conn = sqlite3.connect(self.db_path,check_same_thread=False)
        self.cursor = self.conn.cursor()

    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()

    def execute(self, sql, params=None):
        if not self.conn:
            self.open()
        try:
            if params:
                self.cursor.execute(sql, params)
            else:
                self.cursor.execute(sql)
            self.conn.commit()
        except Exception as e:
            print(f"Error executing SQL: {e}")
            self.conn.rollback()
            raise e

    def query(self, sql, params=None):
        if not self.conn:
            self.open()
        try:
            if params:
                self.cursor.execute(sql, params)
            else:
                self.cursor.execute(sql)
            return self.cursor.fetchall()
        except Exception as e:
            print(f"Error executing SQL: {e}")
            return None
        
